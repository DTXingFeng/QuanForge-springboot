package xyz.xingfeng.QuanForge.service;

import org.json.JSONArray;
import org.json.JSONObject;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import xyz.xingfeng.QuanForge.entity.AiAdviceTrack;
import xyz.xingfeng.QuanForge.entity.AiAlert;
import xyz.xingfeng.QuanForge.repository.AiAdviceTrackRepository;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * AI 建议纸面跟踪器：不真实下单，只用 1m K 线验证带价位建议的盈亏。
 * <ul>
 *   <li>PENDING：等价格触及入场价 → TRACKING；超过 {@link AiAdviceTrack#PENDING_TTL_MINUTES}
 *       未触及 → EXPIRED</li>
 *   <li>TRACKING：先触 TP → WIN，先触 SL → LOSS；同一根 1m K 线同时触发时保守判 LOSS</li>
 *   <li>持仓超过 {@link AiAdviceTrack#TRACKING_TTL_MINUTES} 未触发 → EXPIRED（按当时浮动结算）</li>
 * </ul>
 * 单仓纪律：同品种任意时刻最多一条活跃跟踪（同向新建议跳过、反向新建议
 * 触发旧单市价平仓后开新单），避免同段行情重复计数或多空双计。
 */
@Service
public class AiAdviceTracker {

	private static final Logger log = LoggerFactory.getLogger(AiAdviceTracker.class);

	private static final List<String> ACTIVE = List.of(
			AiAdviceTrack.STATUS_PENDING, AiAdviceTrack.STATUS_TRACKING);

	/** 执行模式：K 线回放推演 */
	private static final String MODE_PAPER = "PAPER";

	/** 执行模式：模拟盘实单（交易所撮合记账） */
	private static final String MODE_DEMO = "DEMO";

	private final AiAdviceTrackRepository repository;
	private final BybitService bybitService;
	private final TelegramBotService telegram;
	private final DemoOrderExecutor executor;
	private final AiConfigService configService;
	@org.springframework.beans.factory.annotation.Autowired
	private ExecutionJournal executionJournal;

	private void journal(AiAdviceTrack track, String kind, String evidence) {
		// Plain unit fixtures have no Spring field injection; production always requires this bean.
		if (executionJournal != null) {
			try { executionJournal.record(track, kind, evidence); }
			catch (org.springframework.dao.DataAccessException e) {
				log.error("执行观察日志写入失败 #{} {}；不能作为完整事件账本", track.getId(), kind);
			}
		}
	}
	/** Closed-bar boundary for PAPER replay; replaceable with a fixed clock in offline tests. */
	private java.time.Clock paperClock = java.time.Clock.systemUTC();

	public AiAdviceTracker(AiAdviceTrackRepository repository, BybitService bybitService,
			TelegramBotService telegram, DemoOrderExecutor executor, AiConfigService configService) {
		this.repository = repository;
		this.bybitService = bybitService;
		this.telegram = telegram;
		this.executor = executor;
		this.configService = configService;
	}

	/**
	 * 为告警创建纸面跟踪（带价位的建议才有）。
	 * <p>
	 * 单仓纪律（模拟真实单仓交易员，同品种任意时刻最多一条活跃跟踪）：
	 * <ul>
	 *   <li>旧 PENDING（等入场）+ 新建议（任意方向）：旧入场价已失去时效 → 旧 EXPIRED，开新</li>
	 *   <li>旧 TRACKING + 新建议<b>同向</b>：跳过不开新跟踪——同一段行情计两遍会虚增期望，
	 *       旧的继续自然结算</li>
	 *   <li>旧 TRACKING + 新建议<b>反向</b>：close-and-reverse——旧单按市价平仓（EXPIRED），
	 *       开新单。真人不会同时持有多空</li>
	 * </ul>
	 * 历史教训：全程取代式清理会掐死 60% 的样本（TRACKING 被强平导致胜率失真），
	 * 因此 TRACKING 绝不因同向新建议被强制结算，只允许反向信号触发市价平仓。
	 */
	@Transactional(propagation = org.springframework.transaction.annotation.Propagation.NOT_SUPPORTED)
	public synchronized void track(AiAlert alert, String action, double entry, double stopLoss, double takeProfit) {
		var cfg = configService.getConfig();
		boolean demo = Boolean.TRUE.equals(cfg.getAutoOrderEnabled());
		// Retain all old Demo ownership, including uncertain submissions. Also protect it when auto-order is off.
		if (repository.findByStatusIn(ACTIVE).stream().anyMatch(t -> MODE_DEMO.equals(t.getExecMode()))) {
			log.info("Demo仍有在途意图或仓位，禁止新增/反转风险");
			return;
		}
		for (AiAdviceTrack old : repository.findBySymbolAndStatusIn(alert.getSymbol(), ACTIVE)) {
			if (AiAdviceTrack.STATUS_PENDING.equals(old.getStatus())) {
				// 实单模式：先撤掉还在挂着的限价委托
				if (MODE_DEMO.equals(old.getExecMode()) && old.getOrderId() != null) {
					try {
						executor.cancel(old.getSymbol(), old.getOrderId());
						// Cancellation acknowledgement is asynchronous: require a terminal exchange fact.
						var d = executor.orderDetail(old.getSymbol(), old.getOrderId());
						double cum = Double.parseDouble(d.optString("cumExecQty", "0"));
						if (cum > 0) {
							if (isTerminalOrder(d.optString("orderStatus"))) {
								enterDemo(old, d.optDouble("avgPrice", old.getEntry()), cum);
							}
							return; // retain ownership; a new signal must not orphan an existing fill
						}
						if (!isTerminalOrder(d.optString("orderStatus"))) {
							return;
						}
					} catch (Exception e) {
						log.warn("撤旧委托失败 {} #{}: {}", old.getSymbol(), old.getId(), e.getMessage());
						return;
					}
				}
				old.setStatus(AiAdviceTrack.STATUS_EXPIRED);
				old.setSettledAt(LocalDateTime.now());
				old.setNote("等入场期间被同品种新建议取代");
				repository.save(old);
				continue;
			}
			// TRACKING 中的旧单
			if (old.getAction().equals(action)) {
				log.info("纸面跟踪跳过: {} 已有同向 TRACKING #{}，避免同段行情重复计数",
						alert.getSymbol(), old.getId());
				return;
			}
			// 反向建议：close-and-reverse
			if (MODE_DEMO.equals(old.getExecMode())) {
				if (!closeDemoReverse(old)) {
					return;
				}
			} else {
				Double last = lastPrice(alert.getSymbol());
				expire(old, "反向建议出现，按市价平仓反转",
						last == null ? null : pricePct(old, last));
			}
		}
		// v4.6 熔断检查：单边行情逆势拦截 + 同向连败冷却（不动老单，只拦新单）
		String blocked = circuitBreakerCheck(alert.getSymbol(), action);
		if (blocked != null) {
			log.info("熔断拦截: {} {} — {}", alert.getSymbol(), action, blocked);
			telegram.send(String.format(Locale.ROOT, "⛔ 熔断拦截 %s %s\n%s\n（建议不执行，等熔断解除）",
					alert.getSymbol(), action, blocked));
			return;
		}
		// v4.8 波动率门槛：低波动时段不开新仓（样本外验证，只拦新单，log-only 不刷 TG）
		String volBlocked = volGateCheck(alert.getSymbol());
		if (volBlocked != null) {
			log.info("波动率门槛拦截: {} {} — {}", alert.getSymbol(), action, volBlocked);
			return;
		}
		AiAdviceTrack t = new AiAdviceTrack();
		t.setAlertId(alert.getId());
		t.setSymbol(alert.getSymbol());
		t.setAction(action);
		t.setEntry(entry);
		// 止损距离硬顶 2.2% 仅 majors：majors 赢单最深回撤 -0.36%，宽止损纯浪费。
		// 山寨不钳制——v4.3 全局钳制的实测教训：ACE 亏损全堆在钳位附近、胜率 41%→31%
		// （幸存者偏差：MAE 只统计了旧止损下活下来的赢单，收窄把本可扛震荡的赢单提前打掉）
		stopLoss = clampStopDistance(alert.getSymbol(), action, entry, stopLoss);
		t.setStopLoss(stopLoss);
		t.setTakeProfit(takeProfit);
		t.setStatus(AiAdviceTrack.STATUS_PENDING);
		t.setSysVersion(xyz.xingfeng.QuanForge.SystemVersion.CURRENT);
		t.setExecMode(MODE_PAPER);
		if (demo) {
			t.setExecMode(MODE_DEMO);
			t.setOrderLinkId("qf-" + java.util.UUID.randomUUID().toString().replace("-", ""));
			t.setDemoSlot("DEMO:" + BybitService.DEFAULT_CREDENTIAL_NAME);
			t.setNote("入场意图已保存；委托结果待核对");
			// Repository transaction must COMMIT before any remote mutation. Unique slot arbitrates other processes.
			try {
				repository.saveAndFlush(t);
			} catch (org.springframework.dao.DataAccessException e) {
				log.warn("Demo意图未提交，禁止发单 {}（可能有并发持有者）", t.getSymbol());
				return;
			}
			try {
				if (executionJournal != null) executionJournal.record(t, "ENTRY_INTENT", "Committed intent; not yet a fill");
				var p = executor.placeEntry(alert.getSymbol(), action, entry, takeProfit, stopLoss,
						cfg.getAutoMarginPct() == null ? 5.0 : cfg.getAutoMarginPct(),
						cfg.getLeverage() == null ? 100 : cfg.getLeverage(), t.getOrderLinkId());
				t.setExecMode(MODE_DEMO);
				t.setOrderId(p.orderId());
				t.setQty(p.qty());
				journal(t, "ENTRY_ACK", "Create response; execution unconfirmed");
				configService.recordEquityBaseline(p.equityUsd());
			} catch (Exception e) {
				log.warn("Demo结果未确认 {} {}；保留意图，禁止回退PAPER", alert.getSymbol(), action);
				t.setNote("入场结果未知；按持久化订单编号对账，禁止重下");
				journal(t, "ENTRY_UNKNOWN", "Reconcile by orderLinkId; never PAPER fallback");
			}
			// Failure here leaves the previously committed intent recoverable by orderLinkId.
			// Do not treat a cancel ACK as compensation for a lost database write.
			repository.saveAndFlush(t);
			return;
		}
		// v4.8.5: 委托挂出后写库可能撞 SQLITE_BUSY_SNAPSHOT（WAL 快照升级冲突，
		// busy_timeout 无效，必须重试）。实盘教训 2026-08-21 ETH：save 失败 → 无跟踪行
		// → 限价单成交后无人设 TP/SL，100x 杠杆裸奔 3 天。写库全败则撤回委托，不留孤儿。
		boolean saved = false;
		for (int attempt = 1; attempt <= 3 && !saved; attempt++) {
			try {
				repository.save(t);
				saved = true;
			} catch (Exception e) {
				log.warn("跟踪行写入失败 {} {} 第{}次: {}", alert.getSymbol(), action, attempt,
						e.getMessage());
				if (attempt < 3) {
					try {
						Thread.sleep(400L);
					} catch (InterruptedException ie) {
						Thread.currentThread().interrupt();
						break;
					}
				}
			}
		}
		if (!saved) {
			log.error("跟踪行写入彻底失败: {} {} — 委托可能已在所", alert.getSymbol(), action);
			if (MODE_DEMO.equals(t.getExecMode()) && t.getOrderId() != null) {
				try {
					executor.cancel(t.getSymbol(), t.getOrderId());
					log.warn("已撤回无跟踪委托 {} {}", t.getSymbol(), t.getOrderId());
				} catch (Exception ce) {
					log.error("撤回委托失败 {} {}: {} — 需人工检查持仓!",
							t.getSymbol(), t.getOrderId(), ce.getMessage());
				}
			}
			telegram.send(String.format(Locale.ROOT,
					"⚠️ 跟踪行写入失败 %s %s，已尝试撤回委托（若撤单失败请人工检查持仓）",
					alert.getSymbol(), action));
			return;
		}
		log.info("纸面跟踪已建立[{}]: {} {} entry={} sl={} tp={}", t.getExecMode(), alert.getSymbol(),
				action, entry, stopLoss, takeProfit);
	}

	/**
	 * 止损距离硬顶 2.2%（仅 BTC/ETH/SOL）：majors 赢单最深回撤 -0.36%，
	 * 宽止损是纯浪费，钳到 2.2% 无副作用。山寨（ACE/HEMI 等）原样放行，
	 * 止损交给 LLM 按结构位判断——全局钳制（v4.3）已被实测否决。
	 */
	private double clampStopDistance(String symbol, String action, double entry, double stopLoss) {
		boolean major = symbol.equals("BTCUSDT") || symbol.equals("ETHUSDT")
				|| symbol.equals("SOLUSDT");
		if (!major) {
			return stopLoss;
		}
		double maxDist = entry * 0.022;
		double dist = "BUY".equals(action) ? entry - stopLoss : stopLoss - entry;
		if (dist > maxDist) {
			double clamped = "BUY".equals(action) ? entry - maxDist : entry + maxDist;
			log.info("{} 止损距离 {}% 超上限，钳制为 2.2%: {} -> {}", symbol,
					String.format(Locale.ROOT, "%.2f", dist / entry * 100), stopLoss, clamped);
			return clamped;
		}
		return stopLoss;
	}

	/**
	 * v4.8 波动率门槛（返回 null=放行）：ATR14% < 0.32% 时不开新仓。
	 * <p>依据：6 个月矩阵样本外验证（tools/vol_gate.py + gate_walkforward.py）——
	 * 低波动时段止损/止盈都走不完 R 倍数位移，全策略家族（机械顺势/LLM）净失血；
	 * 加同门槛后 LLM live 臂 -37.3%→-27.4%，机械臂 3R/4R/5R 全部翻正，
	 * 且 0.25~0.40 区间皆有效（非刀锋参数）。walk-forward 验证时序稳健。
	 * <p>数据取不到时放行（fail-open），只拦新单绝不动老单；不打 TG（低波动期
	 * 触发频繁，刷屏无行动价值），日志留痕即可。
	 */
	private String volGateCheck(String symbol) {
		try {
			String json = bybitService.getPublicRaw("/v5/market/kline",
					Map.of("category", "linear", "symbol", symbol, "interval", "1", "limit", "100"));
			JSONArray list = new JSONObject(json).getJSONObject("result").getJSONArray("list");
			if (list.length() < 20) {
				return null; // 数据不足，放行
			}
			// Bybit 倒序 [0]=最新。翻成正序数组 [high, low, close] 算 TR；元素是 JSONArray
			int n = list.length();
			double[] high = new double[n], low = new double[n], close = new double[n];
			for (int i = 0; i < n; i++) {
				JSONArray o = list.getJSONArray(n - 1 - i);
				high[i] = Double.parseDouble(o.getString(2));
				low[i] = Double.parseDouble(o.getString(3));
				close[i] = Double.parseDouble(o.getString(4));
			}
			// Wilder ATR14（与回测 pandas ewm(alpha=1/14) 同公式）
			double atr = high[0] - low[0];
			for (int i = 1; i < n; i++) {
				double tr = Math.max(high[i] - low[i],
						Math.max(Math.abs(high[i] - close[i - 1]), Math.abs(low[i] - close[i - 1])));
				atr += (tr - atr) / 14.0;
			}
			double atrPct = atr / close[n - 1] * 100;
			if (atrPct < 0.32) {
				return String.format(Locale.ROOT, "低波动 ATR14 %.2f%% < 0.32%%", atrPct);
			}
		} catch (Exception e) {
			log.warn("波动率门槛检查失败 {}: {}", symbol, e.getMessage());
		}
		return null;
	}

	/**
	 * v4.6 双重熔断（单边行情特殊处理，返回 null=放行）：
	 * <ul>
	 *   <li>单边逆势熔断：2h 动量 |move| ≥ 1.2% 时禁止逆势新单——单边行情里逆势剥头皮
	 *       会被一刀刀放血（实测 8/19 夜反弹：5 笔逆势空合计 -1.5%；止损保命但挡不住重复进场）</li>
	 *   <li>连败熔断：同品种同方向最近 2 笔结算全亏 → 该方向冷却 90 分钟不出手</li>
	 * </ul>
	 * 只拦新单，绝不动在场老单（老单的退出由止损/管理器负责）。
	 */
	private String circuitBreakerCheck(String symbol, String action) {
		try {
			// ① 单边逆势：取已收盘的 2 根 1h K 线算动量
			String json = bybitService.getPublicRaw("/v5/market/kline",
					Map.of("category", "linear", "symbol", symbol, "interval", "60", "limit", "3"));
			JSONArray list = new JSONObject(json).getJSONObject("result").getJSONArray("list");
			if (list.length() >= 3) {
				// Bybit 倒序 [0]=当前未收盘 [1]=上一根 [2]=上上根；元素是 JSONArray
				double now = Double.parseDouble(list.getJSONArray(0).getString(4));
				double twoHAgo = Double.parseDouble(list.getJSONArray(2).getString(4));
				double move2h = (now / twoHAgo - 1) * 100;
				boolean counter = move2h >= 1.2 && "SELL".equals(action)
						|| move2h <= -1.2 && "BUY".equals(action);
				if (counter) {
					return String.format(Locale.ROOT, "单边行情: 2h %+.2f%%，禁止逆势%s",
							move2h, action);
				}
			}
		} catch (Exception e) {
			log.warn("单边熔断检查失败 {} : {}", symbol, e.getMessage());
		}
		// ② 同向连败冷却：该品种该方向最近 2 笔结算（90 分钟内）全亏
		LocalDateTime since = LocalDateTime.now().minusMinutes(90);
		List<AiAdviceTrack> recent = repository.findAll().stream()
				.filter(x -> symbol.equals(x.getSymbol()) && action.equals(x.getAction())
						&& (AiAdviceTrack.STATUS_WIN.equals(x.getStatus())
								|| AiAdviceTrack.STATUS_LOSS.equals(x.getStatus()))
						&& x.getSettledAt() != null && x.getSettledAt().isAfter(since))
				.sorted(java.util.Comparator.comparing(AiAdviceTrack::getId).reversed())
				.limit(2).toList();
		if (recent.size() == 2 && recent.stream()
				.allMatch(x -> AiAdviceTrack.STATUS_LOSS.equals(x.getStatus()))) {
			return "同向连败: " + action + " 近90分钟2连亏，冷却中";
		}
		return null;
	}

	/** 实单模式的反向平仓：市价平掉旧仓，从 closed-pnl 读实际盈亏结算 */
	private boolean closeDemoReverse(AiAdviceTrack old) {
		try {
			var pos = executor.position(old.getSymbol());
			if (pos != null) {
				executor.marketClose(old.getSymbol(), pos.getString("side"),
						Double.parseDouble(pos.getString("size")));
				// An accepted close is not a confirmed fill; keep tracking until reconciliation.
				old.setNote("反向建议平仓已请求，等待交易所确认");
				repository.save(old);
				return false;
			}
			var c = executor.closedPnlSince(old.getSymbol(), epochMs(
					old.getEnteredAt() == null ? old.getCreatedAt() : old.getEnteredAt()));
			if (c != null) {
				old.setActualExit(c.avgExit());
				expire(old, "反向建议出现，市价平仓反转", demoPct(c.pnl(), old));
				return true;
			} else {
				return false;
			}
		} catch (Exception e) {
			log.warn("实单反向平仓失败 {} #{}: {}", old.getSymbol(), old.getId(), e.getMessage());
			return false;
		}
	}

	private String truncate(String s, int max) {
		return s == null || s.length() <= max ? s : s.substring(0, max);
	}

	/** 实际盈亏 → 1x 价格变动口径 %（相对开仓名义价值） */
	private Double demoPct(double pnl, AiAdviceTrack t) {
		if (t.getQty() == null || t.getActualEntry() == null || t.getActualEntry() <= 0) {
			return null;
		}
		return pnl / (t.getQty() * t.getActualEntry()) * 100;
	}

	private long epochMs(LocalDateTime time) {
		return time.atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli();
	}

	/** 最新成交价（反向平仓结算用），失败返回 null（不阻塞新跟踪建立） */
	private Double lastPrice(String symbol) {
		try {
			String json = bybitService.getPublicRaw("/v5/market/tickers",
					Map.of("category", "linear", "symbol", symbol));
			JSONArray list = new JSONObject(json).getJSONObject("result").getJSONArray("list");
			return list.isEmpty() ? null : Double.parseDouble(list.getJSONObject(0).getString("lastPrice"));
		} catch (Exception e) {
			log.warn("获取 {} 最新价失败: {}", symbol, e.getMessage());
			return null;
		}
	}

	/** 结算心跳：每分钟检查活跃跟踪 */
	@Scheduled(fixedDelay = 60_000, initialDelay = 45_000)
	@Transactional(propagation = org.springframework.transaction.annotation.Propagation.NOT_SUPPORTED)
	public synchronized void settle() {
		List<AiAdviceTrack> active = repository.findByStatusIn(ACTIVE);
		if (active.isEmpty()) {
			return;
		}
		// 按品种分组拉一次 K 线（单仓纪律下同品种至多一条活跃，分组仅防御性保留）
		Map<String, List<double[]>> candlesBySymbol = new HashMap<>();
		for (AiAdviceTrack t : active) {
			try {
				if (MODE_DEMO.equals(t.getExecMode())) {
					settleDemo(t);
					continue;
				}
				List<double[]> candles = candlesBySymbol.get(t.getSymbol());
				if (candles == null) {
					LocalDateTime deadline = AiAdviceTrack.STATUS_TRACKING.equals(t.getStatus())
							? orNow(t.getEnteredAt()).plusMinutes(trackingTtlMinutes(t))
							: orNow(t.getCreatedAt()).plusMinutes(
									AiAdviceTrack.PENDING_TTL_MINUTES + trackingTtlMinutes(t));
					candles = fetchCandles(t.getSymbol(), earliest(t), epochMs(deadline));
					candlesBySymbol.put(t.getSymbol(), candles);
				}
				settleOne(t, candles);
			} catch (Exception e) {
				log.warn("跟踪结算失败 {} #{}: {}", t.getSymbol(), t.getId(), e.getMessage());
			}
		}
	}

	// ==================== 实单结算（交易所状态机） ====================

	/**
	 * 模拟盘实单的生命周期，全部由交易所事实驱动：
	 * PENDING（限价委托挂着）→ 成交 → TRACKING（TP/SL 由交易所盯）→ 仓位归零 →
	 * 从 closed-pnl 读实际盈亏 → WIN/LOSS。超时由我们主动撤单/市价平仓。
	 */
	private void settleDemo(AiAdviceTrack t) {
		if (AiAdviceTrack.STATUS_PENDING.equals(t.getStatus())) {
			var d = t.getOrderId() == null
					? executor.orderDetailByLink(t.getSymbol(), t.getOrderLinkId())
					: executor.orderDetail(t.getSymbol(), t.getOrderId());
			if (t.getOrderId() == null) {
				String recoveredId = d.optString("orderId");
				if (recoveredId.isBlank()) throw new IllegalStateException("对账未返回委托身份");
				t.setOrderId(recoveredId);
				t.setQty(Double.parseDouble(d.getString("qty")));
				repository.saveAndFlush(t);
			}
			String orderStatus = d.optString("orderStatus", "");
			journal(t, "ORDER_OBSERVED", d.toString());
			double cumQty = Double.parseDouble(d.optString("cumExecQty", "0"));
			switch (orderStatus) {
				case "Filled" -> enterDemo(t, d.optDouble("avgPrice", t.getEntry()), cumQty);
				case "Cancelled", "Rejected", "PartiallyFilledCanceled", "Deactivated" -> {
					if (cumQty > 0) {
						// 部分成交后被撤：剩余仓位交给 TRACKING 状态管理
						enterDemo(t, d.optDouble("avgPrice", t.getEntry()), cumQty);
					} else {
						expire(t, "委托失效: " + orderStatus);
					}
				}
				default -> {
					// New / PartiallyFilled：继续等；超时撤单
					if (minutesSince(orNow(t.getCreatedAt())) > AiAdviceTrack.PENDING_TTL_MINUTES) {
						executor.cancel(t.getSymbol(), t.getOrderId());
						// Re-read after cancellation: fills may race the cancellation request.
						var finalOrder = executor.orderDetail(t.getSymbol(), t.getOrderId());
						if (!isTerminalOrder(finalOrder.optString("orderStatus"))) {
							return;
						}
						cumQty = Double.parseDouble(finalOrder.optString("cumExecQty", "0"));
						if (cumQty > 0) {
							enterDemo(t, finalOrder.optDouble("avgPrice", t.getEntry()), cumQty);
							t.setNote("等入场超时，按已成交部分跟踪");
							repository.save(t);
						} else {
							expire(t, "等入场超时撤单");
						}
					}
				}
			}
			return;
		}

		// TRACKING：仓位归零 = TP/SL/市价平仓已完成
		var pos = executor.position(t.getSymbol());
		if (pos == null) {
			settleDemoClosed(t, t.getNote());
			return;
		}
		if (minutesSince(orNow(t.getEnteredAt())) > trackingTtlMinutes(t)) {
			journal(t, "EXIT_INTENT", "TTL; reduceOnly requested, not confirmed exit");
			executor.marketClose(t.getSymbol(), pos.getString("side"),
					Double.parseDouble(pos.getString("size")));
			t.setNote("持仓超时，市价平仓");
			repository.save(t);
		}
	}

	private boolean isTerminalOrder(String status) {
		return List.of("Filled", "Cancelled", "Rejected", "PartiallyFilledCanceled", "Deactivated").contains(status);
	}

	/**
	 * 持仓 TTL 分档：majors 240 分钟（配合 REBASE 换挡——历史数据 69% 的 majors 亏损单
	 * 在 4h 内回到止盈，2h 会掐死恢复中的单）；山寨维持 120 分钟（扛单平均再跌 6%，
	 * 越拖越危险）。已换挡的 majors 单也按 4h 封顶。
	 */
	private int trackingTtlMinutes(AiAdviceTrack t) {
		boolean major = t.getSymbol() != null && (t.getSymbol().equals("BTCUSDT")
				|| t.getSymbol().equals("ETHUSDT") || t.getSymbol().equals("SOLUSDT"));
		return major ? 240 : AiAdviceTrack.TRACKING_TTL_MINUTES;
	}

	/** 限价委托成交 → TRACKING，记录真实入场价与数量，并设置 TP/SL */
	private void enterDemo(AiAdviceTrack t, double avgPrice, double qty) {
		t.setStatus(AiAdviceTrack.STATUS_TRACKING);
		t.setActualEntry(avgPrice > 0 ? avgPrice : t.getEntry());
		if (qty > 0) {
			t.setQty(qty);
		}
		t.setEnteredAt(LocalDateTime.now());
		repository.save(t);
		log.info("实单跟踪 #{} {} 已成交入场 {} qty={}", t.getId(), t.getSymbol(),
				t.getActualEntry(), t.getQty());
		// 新委托已经随单附保护；这里复核/补设，兼容升级前遗留的不带保护委托。
		// v4.8.1: 失败先退避重试（2s/4s ×2）——瞬时限频/网络抖动不应导致保护性平仓
		// （实测 3+ 次因瞬时失败被平仓，白亏 ~0.5%）
		boolean set = false;
		Exception last = null;
		for (int attempt = 1; attempt <= 3 && !set; attempt++) {
			try {
				executor.setTradingStop(t.getSymbol(), t.getAction(), t.getTakeProfit(), t.getStopLoss());
				journal(t, "PROTECTION_ACK", "Trading stop response; exchange observation still required");
				set = true;
			} catch (Exception e) {
				last = e;
				log.warn("TP/SL 设置失败 #{} 第{}次: {}", t.getId(), attempt, e.getMessage());
				if (attempt < 3) {
					try {
						Thread.sleep(attempt * 2000L);
					} catch (InterruptedException ie) {
						Thread.currentThread().interrupt();
						break;
					}
				}
			}
		}
		if (!set) {
			log.warn("TP/SL 重试全败 #{}，保护性市价平仓: {}", t.getId(),
					last == null ? "?" : last.getMessage());
			try {
				var pos = executor.position(t.getSymbol());
				if (pos != null) {
					executor.marketClose(t.getSymbol(), pos.getString("side"),
							Double.parseDouble(pos.getString("size")));
				}
			} catch (Exception closeEx) {
				log.error("保护性平仓也失败 #{}: {}", t.getId(), closeEx.getMessage());
			}
			t.setNote("TP/SL设置失败(重试3次后)，保护性平仓");
			repository.save(t);
		}
	}

	/** 仓位已归零：从 closed-pnl 读实际盈亏结算（绝对准确的记账来源） */
	private void settleDemoClosed(AiAdviceTrack t, String note) {
		long since = epochMs(t.getEnteredAt() == null ? t.getCreatedAt() : t.getEnteredAt());
		var c = executor.closedPnlSince(t.getSymbol(), since - 60_000);
		if (c == null) {
			// 平仓记录尚未生成（异步延迟），下轮心跳再核
			log.info("实单跟踪 #{} 仓位已平但 closed-pnl 暂无记录，下轮核对", t.getId());
			return;
		}
		t.setActualExit(c.avgExit());
		String status = c.pnl() >= 0 ? AiAdviceTrack.STATUS_WIN : AiAdviceTrack.STATUS_LOSS;
		Double pct = demoPct(c.pnl(), t);
		if (pct != null) {
			settleTrack(t, status, pct, note);
		} else {
			settleTrack(t, status, 0, note);
		}
		log.info("实单结算 #{} {}: pnl={} 出场价={}", t.getId(), t.getSymbol(),
				String.format(Locale.ROOT, "%.4f", c.pnl()), c.avgExit());
	}

	// ==================== 单条结算 ====================

	private void settleOne(AiAdviceTrack t, List<double[]> candles) {
		LocalDateTime since = AiAdviceTrack.STATUS_TRACKING.equals(t.getStatus())
				? orNow(t.getEnteredAt()) : orNow(t.getCreatedAt());
		boolean buy = "BUY".equals(t.getAction());
		// 入场判定只看建议发出之后开盘的K线；持仓判定只看入场之后开盘的K线
		long lastClosedStart = paperClock.millis() / 60_000 * 60_000 - 60_000;
		LocalDateTime filterSince = since;
		if (AiAdviceTrack.STATUS_TRACKING.equals(t.getStatus())) {
			for (double[] c : candles) {
				if (c[0] <= lastClosedStart && candleTime(c).equals(since)
						&& candleTime(c).isAfter(orNow(t.getCreatedAt()))
						&& (buy ? c[2] <= t.getStopLoss() : c[1] >= t.getStopLoss())) {
					settleTrack(t, AiAdviceTrack.STATUS_LOSS, pricePct(t, t.getStopLoss()),
							"入场同根K线触止损，时序未知保守判损");
					return;
				}
			}
		}
		List<double[]> after = candles.stream()
				.filter(c -> c[0] <= lastClosedStart && candleTime(c).isAfter(filterSince))
				.toList();

		if (AiAdviceTrack.STATUS_PENDING.equals(t.getStatus())) {
			boolean touched = false;
			LocalDateTime entryDeadline = since.plusMinutes(AiAdviceTrack.PENDING_TTL_MINUTES);
			for (double[] c : after) {
				if (candleTime(c).isAfter(entryDeadline)) {
					break;
				}
				if (buy ? c[2] <= t.getEntry() : c[1] >= t.getEntry()) {
					t.setStatus(AiAdviceTrack.STATUS_TRACKING);
					t.setEnteredAt(candleTime(c));
					t.setNote(null);
					touched = true;
					// OHLC cannot establish entry/exit order. Charge a same-bar stop conservatively;
					// never award a take-profit that could have occurred before the fill.
					if (buy ? c[2] <= t.getStopLoss() : c[1] >= t.getStopLoss()) {
						settleTrack(t, AiAdviceTrack.STATUS_LOSS, pricePct(t, t.getStopLoss()),
								"入场同根K线触止损，时序未知保守判损");
						return;
					}
					break;
				}
			}
			if (AiAdviceTrack.STATUS_TRACKING.equals(t.getStatus())) {
				repository.save(t);
				log.info("纸面跟踪 #{} {} 已触及入场 {}", t.getId(), t.getSymbol(), t.getEntry());
				// Continue through the rest of the replay immediately; no heartbeat may skip an exit.
				since = t.getEnteredAt();
				LocalDateTime entered = since;
				after = after.stream().filter(c -> candleTime(c).isAfter(entered)).toList();
			} else {
				if (!touched && minutesSince(since) > AiAdviceTrack.PENDING_TTL_MINUTES) {
					expire(t, "超时未触及入场价");
				}
				return;
			}
		}

		// TRACKING：先触 SL 判 LOSS（保守），再触 TP 判 WIN
		LocalDateTime exitDeadline = since.plusMinutes(trackingTtlMinutes(t));
		double last = t.getEntry();
		boolean haveClose = false;
		for (double[] c : after) {
			if (candleTime(c).plusMinutes(1).isAfter(exitDeadline)) {
				break;
			}
			last = c[3];
			haveClose = true;
			boolean hitSl = buy ? c[2] <= t.getStopLoss() : c[1] >= t.getStopLoss();
			boolean hitTp = buy ? c[1] >= t.getTakeProfit() : c[2] <= t.getTakeProfit();
			if (hitSl) {
				settleTrack(t, AiAdviceTrack.STATUS_LOSS, pricePct(t, t.getStopLoss()),
						hitTp ? "同根K线双触发，保守判损" : null);
				return;
			}
			if (hitTp) {
				settleTrack(t, AiAdviceTrack.STATUS_WIN, pricePct(t, t.getTakeProfit()), null);
				return;
			}
		}
		if (minutesSince(since) > trackingTtlMinutes(t) && haveClose) {
			expire(t, "持仓超时，按TTL时点已收盘价结算", pricePct(t, last));
		}
	}

	private void settleTrack(AiAdviceTrack t, String status, double resultPct, String note) {
		t.setStatus(status);
		t.setDemoSlot(null);
		t.setSettledAt(LocalDateTime.now());
		t.setResultPct(round2(resultPct));
		t.setNote(note);
		repository.save(t);
		journal(t, "SETTLED_ESTIMATE", "Legacy result_pct is not a reconciled full-cost net ledger");
		log.info("纸面跟踪 #{} {} 结算: {} {}%", t.getId(), t.getSymbol(), status,
				String.format(Locale.ROOT, "%.2f", resultPct));
		if (AiAdviceTrack.STATUS_WIN.equals(status) || AiAdviceTrack.STATUS_LOSS.equals(status)) {
			telegram.notifySettle(t);
		}
	}

	private void expire(AiAdviceTrack t, String note) {
		expire(t, note, null);
	}

	private void expire(AiAdviceTrack t, String note, Double resultPct) {
		t.setStatus(AiAdviceTrack.STATUS_EXPIRED);
		t.setDemoSlot(null);
		t.setSettledAt(LocalDateTime.now());
		t.setNote(note);
		if (resultPct != null) {
			t.setResultPct(round2(resultPct));
		}
		repository.save(t);
		log.info("纸面跟踪 #{} {} 过期: {}", t.getId(), t.getSymbol(), note);
	}

	/** 有利方向的价格变动 %：BUY 用 (p-entry)/entry，SELL 用 (entry-p)/entry */
	private double pricePct(AiAdviceTrack t, double price) {
		boolean buy = "BUY".equals(t.getAction());
		return buy ? (price - t.getEntry()) / t.getEntry() * 100
				: (t.getEntry() - price) / t.getEntry() * 100;
	}

	// ==================== 统计 ====================

	/** 胜率统计（前端展示）：以 WIN+LOSS 为分母，EXPIRED 不计入胜率 */
	@Transactional(readOnly = true)
	public Map<String, Object> stats() {
		List<AiAdviceTrack> all = repository.findAll();
		long wins = all.stream().filter(t -> AiAdviceTrack.STATUS_WIN.equals(t.getStatus())).count();
		long losses = all.stream().filter(t -> AiAdviceTrack.STATUS_LOSS.equals(t.getStatus())).count();
		long expired = all.stream().filter(t -> AiAdviceTrack.STATUS_EXPIRED.equals(t.getStatus())).count();
		long active = all.stream().filter(t -> ACTIVE.contains(t.getStatus())).count();
		long settled = wins + losses;
		double winRate = settled == 0 ? Double.NaN : (double) wins / settled * 100;
		double avgResult = all.stream()
				.filter(t -> t.getResultPct() != null
						&& (AiAdviceTrack.STATUS_WIN.equals(t.getStatus())
								|| AiAdviceTrack.STATUS_LOSS.equals(t.getStatus())))
				.mapToDouble(t -> t.getResultPct() == null ? 0 : t.getResultPct())
				.average().orElse(Double.NaN);
		Map<String, Object> m = new HashMap<>();
		m.put("total", all.size());
		m.put("wins", wins);
		m.put("losses", losses);
		m.put("expired", expired);
		m.put("active", active);
		m.put("settled", settled);
		m.put("winRate", Double.isNaN(winRate) ? null : round2(winRate));
		m.put("avgResultPct", Double.isNaN(avgResult) ? null : round2(avgResult));
		// 按体系版本分组（复盘用）：null 为打戳功能上线前的历史数据，标记为 legacy
		Map<String, Map<String, Object>> byVersion = new java.util.LinkedHashMap<>();
		all.stream()
				.collect(java.util.stream.Collectors.groupingBy(
						t -> t.getSysVersion() == null ? "legacy" : t.getSysVersion()))
				.forEach((ver, list) -> {
					long w = list.stream().filter(t -> AiAdviceTrack.STATUS_WIN.equals(t.getStatus())).count();
					long l = list.stream().filter(t -> AiAdviceTrack.STATUS_LOSS.equals(t.getStatus())).count();
					long s = w + l;
					Map<String, Object> vm = new HashMap<>();
					vm.put("total", list.size());
					vm.put("settled", s);
					vm.put("wins", w);
					vm.put("losses", l);
					vm.put("winRate", s == 0 ? null : round2(w * 100.0 / s));
					byVersion.put(ver, vm);
				});
		m.put("byVersion", byVersion);
		// 按执行模式分组：DEMO=模拟盘实单（交易所记账）/ PAPER=K线回放推演
		Map<String, Map<String, Object>> byExec = new java.util.LinkedHashMap<>();
		all.stream()
				.collect(java.util.stream.Collectors.groupingBy(
						t -> t.getExecMode() == null ? MODE_PAPER : t.getExecMode()))
				.forEach((mode, list) -> {
					long w = list.stream().filter(t -> AiAdviceTrack.STATUS_WIN.equals(t.getStatus())).count();
					long l = list.stream().filter(t -> AiAdviceTrack.STATUS_LOSS.equals(t.getStatus())).count();
					long s = w + l;
					Map<String, Object> em = new HashMap<>();
					em.put("total", list.size());
					em.put("settled", s);
					em.put("wins", w);
					em.put("losses", l);
					em.put("winRate", s == 0 ? null : round2(w * 100.0 / s));
					Double avg = list.stream()
							.filter(t -> t.getResultPct() != null && s > 0
									&& (AiAdviceTrack.STATUS_WIN.equals(t.getStatus())
											|| AiAdviceTrack.STATUS_LOSS.equals(t.getStatus())))
							.mapToDouble(AiAdviceTrack::getResultPct)
							.average().orElse(Double.NaN);
					em.put("avgResultPct", Double.isNaN(avg) ? null : round2(avg));
					byExec.put(mode, em);
				});
		m.put("byExecMode", byExec);
		return m;
	}

	@Transactional(readOnly = true)
	public List<AiAdviceTrack> recent(int limit) {
		List<AiAdviceTrack> all = repository.findTop50ByOrderByCreatedAtDesc();
		int n = Math.min(Math.max(limit, 1), all.size());
		return all.subList(0, n);
	}

	// ==================== 数据 ====================

	/** 拉指定时间之后的 1m K 线：[timeMillis, high, low, close] */
	private List<double[]> fetchCandles(String symbol, LocalDateTime since, long deadlineMs) throws Exception {
		long sinceMs = epochMs(since);
		long first = sinceMs / 60_000 * 60_000 + 60_000;
		long lastClosed = paperClock.millis() / 60_000 * 60_000 - 60_000;
		// Even after a long outage only entry TTL + maximum holding TTL can affect this track.
		long last = Math.min(lastClosed, deadlineMs / 60_000 * 60_000 - 60_000);
		if (last - first > (AiAdviceTrack.PENDING_TTL_MINUTES + 240L) * 60_000) {
			throw new IllegalStateException("PAPER回放时间窗超预算，保留跟踪");
		}
		if (first > last) {
			return List.of();
		}
		java.util.NavigableMap<Long, double[]> rows = new java.util.TreeMap<>();
		long pageEnd = last;
		for (int page = 0; page < 4 && pageEnd >= first; page++) {
			String json = bybitService.getPublicRaw("/v5/market/kline", Map.of(
					"category", "linear", "symbol", symbol, "interval", "1", "limit", "1000",
					"start", Long.toString(first), "end", Long.toString(pageEnd)));
			JSONObject resp = new JSONObject(json);
			if (resp.getInt("retCode") != 0) {
				throw new IllegalStateException("PAPER回放行情失败: " + resp.optString("retMsg"));
			}
			JSONArray list = resp.getJSONObject("result").getJSONArray("list");
			long minimum = Long.MAX_VALUE;
			for (int i = 0; i < list.length(); i++) {
				JSONArray k = list.getJSONArray(i);
				long start = Long.parseLong(k.getString(0));
				if (start < first || start > pageEnd) {
					continue;
				}
				double high = Double.parseDouble(k.getString(2));
				double low = Double.parseDouble(k.getString(3));
				double close = Double.parseDouble(k.getString(4));
				if (start % 60_000 != 0 || !Double.isFinite(high) || !Double.isFinite(low)
						|| !Double.isFinite(close) || low <= 0 || high < low || close < low || close > high) {
					throw new IllegalStateException("PAPER回放无效K线，保留跟踪: " + start);
				}
				double[] row = { start, high, low, close };
				double[] previous = rows.putIfAbsent(start, row);
				if (previous != null && !java.util.Arrays.equals(previous, row)) {
					throw new IllegalStateException("PAPER回放重复K线冲突，保留跟踪: " + start);
				}
				minimum = Math.min(minimum, start);
			}
			if (minimum == Long.MAX_VALUE) {
				throw new IllegalStateException("PAPER回放历史缺失/分页无进展，保留跟踪");
			}
			pageEnd = minimum - 60_000;
		}
		if (pageEnd >= first) {
			throw new IllegalStateException("PAPER回放超4页预算，保留跟踪等待补数");
		}
		for (long expected = first; expected <= last; expected += 60_000) {
			if (!rows.containsKey(expected)) {
				throw new IllegalStateException("PAPER回放K线缺口，保留跟踪: " + expected);
			}
		}
		return new java.util.ArrayList<>(rows.values());
	}

	private LocalDateTime candleTime(double[] c) {
		return LocalDateTime.ofInstant(java.time.Instant.ofEpochMilli((long) c[0]),
				java.time.ZoneId.systemDefault());
	}

	private LocalDateTime earliest(AiAdviceTrack t) {
		LocalDateTime created = orNow(t.getCreatedAt());
		LocalDateTime entered = orNow(t.getEnteredAt());
		return entered.isBefore(created) ? entered : created;
	}

	private LocalDateTime orNow(LocalDateTime t) {
		return t == null ? LocalDateTime.now() : t;
	}

	private long minutesSince(LocalDateTime t) {
		return java.time.Duration.between(t, LocalDateTime.now()).toMinutes();
	}

	private double round2(double v) {
		return Double.isNaN(v) ? v : Math.round(v * 100) / 100.0;
	}
}
