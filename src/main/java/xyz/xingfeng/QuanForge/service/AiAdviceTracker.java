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
	@Transactional
	public void track(AiAlert alert, String action, double entry, double stopLoss, double takeProfit) {
		var cfg = configService.getConfig();
		boolean demo = Boolean.TRUE.equals(cfg.getAutoOrderEnabled());
		for (AiAdviceTrack old : repository.findBySymbolAndStatusIn(alert.getSymbol(), ACTIVE)) {
			if (AiAdviceTrack.STATUS_PENDING.equals(old.getStatus())) {
				// 实单模式：先撤掉还在挂着的限价委托
				if (demo && MODE_DEMO.equals(old.getExecMode()) && old.getOrderId() != null) {
					try {
						executor.cancel(old.getSymbol(), old.getOrderId());
						// 撤单 ≠ 无成交：轮询间隙里可能已部分/全部成交，核查遗留仓位并平掉
						var d = executor.orderDetail(old.getSymbol(), old.getOrderId());
						double cum = Double.parseDouble(d.optString("cumExecQty", "0"));
						if (cum > 0) {
							var pos = executor.position(old.getSymbol());
							if (pos != null) {
								executor.marketClose(old.getSymbol(), pos.getString("side"),
										Double.parseDouble(pos.getString("size")));
							}
							var c = executor.closedPnlSince(old.getSymbol(), epochMs(
									old.getCreatedAt()));
							if (c != null) {
								old.setActualExit(c.avgExit());
							}
							expire(old, "取代时发现已成交，平仓结算", null);
							continue;
						}
					} catch (Exception e) {
						log.warn("撤旧委托失败 {} #{}: {}", old.getSymbol(), old.getId(), e.getMessage());
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
				closeDemoReverse(old);
			} else {
				Double last = lastPrice(alert.getSymbol());
				expire(old, "反向建议出现，按市价平仓反转",
						last == null ? null : pricePct(old, last));
			}
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
			try {
				var p = executor.placeEntry(alert.getSymbol(), action, entry, stopLoss, takeProfit,
						cfg.getAutoMarginPct() == null ? 5.0 : cfg.getAutoMarginPct(),
						cfg.getLeverage() == null ? 100 : cfg.getLeverage());
				t.setExecMode(MODE_DEMO);
				t.setOrderId(p.orderId());
				t.setQty(p.qty());
				configService.recordEquityBaseline(p.equityUsd());
			} catch (Exception e) {
				log.warn("模拟盘下单失败，回退纸面跟踪 {} {}: {}", alert.getSymbol(), action, e.getMessage());
				t.setNote("模拟盘下单失败(" + truncate(e.getMessage(), 60) + ")，回退纸面");
			}
		}
		repository.save(t);
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

	/** 实单模式的反向平仓：市价平掉旧仓，从 closed-pnl 读实际盈亏结算 */
	private void closeDemoReverse(AiAdviceTrack old) {
		try {
			var pos = executor.position(old.getSymbol());
			if (pos != null) {
				executor.marketClose(old.getSymbol(), pos.getString("side"),
						Double.parseDouble(pos.getString("size")));
			}
			var c = executor.closedPnlSince(old.getSymbol(), epochMs(
					old.getEnteredAt() == null ? old.getCreatedAt() : old.getEnteredAt()));
			if (c != null) {
				old.setActualExit(c.avgExit());
				expire(old, "反向建议出现，市价平仓反转", demoPct(c.pnl(), old));
			} else {
				expire(old, "反向建议平仓，盈亏待下轮核对", null);
			}
		} catch (Exception e) {
			log.warn("实单反向平仓失败 {} #{}: {}", old.getSymbol(), old.getId(), e.getMessage());
			expire(old, "反向建议平仓失败: " + truncate(e.getMessage(), 60), null);
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
	@Transactional
	public void settle() {
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
					candles = fetchCandles(t.getSymbol(), earliest(t));
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
			var d = executor.orderDetail(t.getSymbol(), t.getOrderId());
			String orderStatus = d.optString("orderStatus", "");
			double cumQty = Double.parseDouble(d.optString("cumExecQty", "0"));
			switch (orderStatus) {
				case "Filled" -> enterDemo(t, d.optDouble("avgPrice", t.getEntry()), cumQty);
				case "Cancelled", "Rejected" -> {
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
						if (cumQty > 0) {
							enterDemo(t, d.optDouble("avgPrice", t.getEntry()), cumQty);
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
		if (minutesSince(orNow(t.getEnteredAt())) > trackingTtlMinutes(t)
				&& t.getNote() == null) {
			executor.marketClose(t.getSymbol(), pos.getString("side"),
					Double.parseDouble(pos.getString("size")));
			t.setNote("持仓超时，市价平仓");
			repository.save(t);
		}
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
		// 成交后才设 TP/SL（挂单附带会被 Bybit 按现价校验拒绝，见 placeEntry 注释）
		try {
			executor.setTradingStop(t.getSymbol(), t.getAction(), t.getTakeProfit(), t.getStopLoss());
		} catch (Exception e) {
			log.warn("TP/SL 设置失败 #{}，保护性市价平仓: {}", t.getId(), e.getMessage());
			try {
				var pos = executor.position(t.getSymbol());
				if (pos != null) {
					executor.marketClose(t.getSymbol(), pos.getString("side"),
							Double.parseDouble(pos.getString("size")));
				}
			} catch (Exception closeEx) {
				log.error("保护性平仓也失败 #{}: {}", t.getId(), closeEx.getMessage());
			}
			t.setNote("TP/SL设置失败，保护性平仓");
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
		List<double[]> after = candles.stream()
				.filter(c -> candleTime(c).isAfter(since))
				.toList();

		if (AiAdviceTrack.STATUS_PENDING.equals(t.getStatus())) {
			boolean touched = false;
			for (double[] c : after) {
				if (buy ? c[1] >= t.getEntry() : c[2] <= t.getEntry()) {
					t.setStatus(AiAdviceTrack.STATUS_TRACKING);
					t.setEnteredAt(candleTime(c));
					t.setNote(null);
					touched = true;
					break;
				}
			}
			if (AiAdviceTrack.STATUS_TRACKING.equals(t.getStatus())) {
				repository.save(t);
				log.info("纸面跟踪 #{} {} 已触及入场 {}", t.getId(), t.getSymbol(), t.getEntry());
				return; // 入场后的 TP/SL 从下一次心跳开始盯（避免同根K线抢先判定）
			}
			if (!touched && minutesSince(since) > AiAdviceTrack.PENDING_TTL_MINUTES) {
				expire(t, "超时未触及入场价");
			}
			return;
		}

		// TRACKING：先触 SL 判 LOSS（保守），再触 TP 判 WIN
		for (double[] c : after) {
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
		if (minutesSince(since) > trackingTtlMinutes(t)) {
			double last = candles.isEmpty() ? t.getEntry() : candles.get(candles.size() - 1)[3];
			expire(t, "持仓超时，按现价结算", pricePct(t, last));
		}
	}

	private void settleTrack(AiAdviceTrack t, String status, double resultPct, String note) {
		t.setStatus(status);
		t.setSettledAt(LocalDateTime.now());
		t.setResultPct(round2(resultPct));
		t.setNote(note);
		repository.save(t);
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
	private List<double[]> fetchCandles(String symbol, LocalDateTime since) throws Exception {
		String json = bybitService.getPublicRaw("/v5/market/kline",
				Map.of("category", "linear", "symbol", symbol, "interval", "1", "limit", "200"));
		JSONObject resp = new JSONObject(json);
		if (resp.getInt("retCode") != 0) {
			throw new IllegalStateException("Bybit kline: " + resp.getString("retMsg"));
		}
		JSONArray list = resp.getJSONObject("result").getJSONArray("list");
		long sinceMs = since.minusMinutes(2).atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli();
		java.util.List<double[]> rows = new java.util.ArrayList<>();
		for (int i = 0; i < list.length(); i++) {
			JSONArray k = list.getJSONArray(i);
			double start = Double.parseDouble(k.getString(0));
			if ((long) start < sinceMs) {
				continue;
			}
			// Bybit 元素顺序 [start, open, high, low, close, volume]，原始倒序
			rows.add(new double[] { start, Double.parseDouble(k.getString(2)),
					Double.parseDouble(k.getString(3)), Double.parseDouble(k.getString(4)) });
		}
		java.util.Collections.reverse(rows);
		return rows;
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
