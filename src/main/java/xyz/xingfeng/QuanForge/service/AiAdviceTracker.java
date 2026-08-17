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
 * 同品种同时只保留一条活跃跟踪（新建议发出时旧活跃记录标记取代过期），
 * 避免同一品种多条建议重复统计。
 */
@Service
public class AiAdviceTracker {

	private static final Logger log = LoggerFactory.getLogger(AiAdviceTracker.class);

	private static final List<String> ACTIVE = List.of(
			AiAdviceTrack.STATUS_PENDING, AiAdviceTrack.STATUS_TRACKING);

	private final AiAdviceTrackRepository repository;
	private final BybitService bybitService;
	private final TelegramBotService telegram;

	public AiAdviceTracker(AiAdviceTrackRepository repository, BybitService bybitService,
			TelegramBotService telegram) {
		this.repository = repository;
		this.bybitService = bybitService;
		this.telegram = telegram;
	}

	/**
	 * 为告警创建纸面跟踪（带价位的建议才有）。
	 * 纸面测量允许多条并行：TRACKING（已入场）的让市场自然结算，只有 PENDING
	 * （等入场）的会被同品种新建议取代——旧建议还没入场就来了新建议，
	 * 旧入场价已失去时效，保留只会污染样本。这是实测教训：全程取代式清理
	 * 会掐死 60% 的样本，胜率统计严重失真。
	 */
	@Transactional
	public void track(AiAlert alert, String action, double entry, double stopLoss, double takeProfit) {
		for (AiAdviceTrack old : repository.findBySymbolAndStatusIn(alert.getSymbol(), ACTIVE)) {
			if (!AiAdviceTrack.STATUS_PENDING.equals(old.getStatus())) {
				continue;
			}
			old.setStatus(AiAdviceTrack.STATUS_EXPIRED);
			old.setSettledAt(LocalDateTime.now());
			old.setNote("等入场期间被同品种新建议取代");
			repository.save(old);
		}
		AiAdviceTrack t = new AiAdviceTrack();
		t.setAlertId(alert.getId());
		t.setSymbol(alert.getSymbol());
		t.setAction(action);
		t.setEntry(entry);
		t.setStopLoss(stopLoss);
		t.setTakeProfit(takeProfit);
		t.setStatus(AiAdviceTrack.STATUS_PENDING);
		t.setSysVersion(xyz.xingfeng.QuanForge.SystemVersion.CURRENT);
		repository.save(t);
		log.info("纸面跟踪已建立: {} {} entry={} sl={} tp={}", alert.getSymbol(), action,
				entry, stopLoss, takeProfit);
	}

	/** 结算心跳：每分钟检查活跃跟踪 */
	@Scheduled(fixedDelay = 60_000, initialDelay = 45_000)
	@Transactional
	public void settle() {
		List<AiAdviceTrack> active = repository.findByStatusIn(ACTIVE);
		if (active.isEmpty()) {
			return;
		}
		// 按品种分组拉一次 K 线，同品种多条（理论只有一条）复用
		Map<String, List<double[]>> candlesBySymbol = new HashMap<>();
		for (AiAdviceTrack t : active) {
			try {
				List<double[]> candles = candlesBySymbol.get(t.getSymbol());
				if (candles == null) {
					candles = fetchCandles(t.getSymbol(), earliest(t));
					candlesBySymbol.put(t.getSymbol(), candles);
				}
				settleOne(t, candles);
			} catch (Exception e) {
				log.warn("纸面跟踪结算失败 {} #{}: {}", t.getSymbol(), t.getId(), e.getMessage());
			}
		}
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
		if (minutesSince(since) > AiAdviceTrack.TRACKING_TTL_MINUTES) {
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
