package xyz.xingfeng.QuanForge.service;

import okhttp3.MediaType;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import org.json.JSONArray;
import org.json.JSONObject;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import xyz.xingfeng.QuanForge.client.ProxiedHttpClients;
import xyz.xingfeng.QuanForge.entity.AiAdviceTrack;
import xyz.xingfeng.QuanForge.entity.AiConfig;
import xyz.xingfeng.QuanForge.repository.AiAdviceTrackRepository;

import java.util.List;
import java.util.Locale;

/**
 * 持仓动态管理器：入场后的第二道研判。
 * <p>
 * 实单成交后 TP/SL 静止挂在交易所，本管理器每隔几分钟对每个 DEMO 持仓
 * 做一次轻量复查（行情快照 + 统计模型方向 + LLM 决策），允许：
 * <ul>
 *   <li>CLOSE：提前离场——浮盈但动能衰竭将回吐 / 将破关键位宁可小亏 / 模型转向</li>
 *   <li>MOVE_SL：止损向有利方向移动（锁利润），禁止放宽</li>
 *   <li>MOVE_TP：止盈靠近（提前落袋），BUY 只能下调 / SELL 只能上调</li>
 *   <li>HOLD：默认——入场逻辑未破坏就让利润跑</li>
 * </ul>
 * 决策审计：动作与理由写入 track.note（结算推送可见）；CLOSE 的实际盈亏
 * 仍由结算心跳从 closed-pnl 读取（绝对准确口径不变）。
 */
@Service
public class PositionManagerService {

	private static final Logger log = LoggerFactory.getLogger(PositionManagerService.class);

	/** 复查周期：5 分钟（剥头皮持仓分钟级演化，太疏会错过"转弱"窗口） */
	private static final long REVIEW_INTERVAL_MS = 300_000;

	/** 入场后最短观察期：刚成交 3 分钟内不看（让走势先走出来） */
	private static final int MIN_AGE_MINUTES = 3;

	private final AiAdviceTrackRepository repository;
	private final DemoOrderExecutor executor;
	private final BybitService bybitService;
	private final ProxiedHttpClients clients;
	private final AiConfigService configService;
	private final AiToolRegistry toolRegistry;

	public PositionManagerService(AiAdviceTrackRepository repository, DemoOrderExecutor executor,
			BybitService bybitService, ProxiedHttpClients clients, AiConfigService configService,
			AiToolRegistry toolRegistry) {
		this.repository = repository;
		this.executor = executor;
		this.bybitService = bybitService;
		this.clients = clients;
		this.configService = configService;
		this.toolRegistry = toolRegistry;
	}

	@Scheduled(fixedDelay = REVIEW_INTERVAL_MS, initialDelay = 180_000)
	@Transactional
	public void review() {
		AiConfig config = configService.getConfig();
		if (!Boolean.TRUE.equals(config.getAutoOrderEnabled()) || !configService.isConfigured()) {
			return;
		}
		List<AiAdviceTrack> tracking = repository.findByStatusIn(
						List.of(AiAdviceTrack.STATUS_TRACKING)).stream()
				.filter(t -> "DEMO".equals(t.getExecMode()))
				.toList();
		for (AiAdviceTrack t : tracking) {
			try {
				reviewOne(config, t);
			} catch (Exception e) {
				log.warn("持仓复查失败 {} #{}: {}", t.getSymbol(), t.getId(), e.getMessage());
			}
		}
	}

	private void reviewOne(AiConfig config, AiAdviceTrack t) throws Exception {
		if (t.getEnteredAt() == null
				|| System.currentTimeMillis() - epochMs(t.getEnteredAt()) < MIN_AGE_MINUTES * 60_000L) {
			return;
		}
		JSONObject d = judge(config, t);
		String decision = d.optString("decision", "HOLD").toUpperCase(Locale.ROOT);
		String reason = truncate(d.optString("reason", ""), 60);
		switch (decision) {
			case "CLOSE" -> applyClose(t, reason);
			case "MOVE_SL", "MOVE_TP" -> applyMove(t, d, reason);
			case "REBASE" -> applyRebase(t, d, reason);
			default -> log.debug("持仓复查 #{} {}: HOLD", t.getId(), t.getSymbol());
		}
	}

	// ==================== 动作执行 ====================

	/** majors 集合：仅主流币允许 REBASE（数据依据：majors 亏损多为震荡噪音可扛，山寨扛单平均再跌 6%） */
	private static final java.util.Set<String> REBASE_ALLOWED =
			java.util.Set.of("BTCUSDT", "ETHUSDT", "SOLUSDT");

	/** REBASE 后总风险硬顶（账户 %，含浮亏） */
	private static final double REBASE_MAX_RISK_PCT = 2.0;

	/**
	 * 换挡扛单（仅 majors）：亏损确认为震荡噪音、高周期结构未破时，
	 * 把止损从剥头皮结构位上移到高周期（小时/日线）结构失效位，
	 * 研判从剥头皮升格为波段。围栏：
	 * <ul>
	 *   <li>仅 BTC/ETH/SOL；山寨禁止（扛单平均再跌 6%，19% 极端）</li>
	 *   <li>结构保护：新止损必须在高周期区间失效位之外，且当前价未破该结构</li>
	 *   <li>风险硬顶：按新止损计算的总亏损（浮亏+剩余风险）≤ 2% 账户</li>
	 *   <li>每单最多换挡一次</li>
	 * </ul>
	 */
	private void applyRebase(AiAdviceTrack t, JSONObject d, String reason) {
		if (!REBASE_ALLOWED.contains(t.getSymbol())) {
			log.info("拒绝 REBASE（山寨禁用）#{} {}", t.getId(), t.getSymbol());
			return;
		}
		if (t.getRebasedAt() != null) {
			log.info("拒绝 REBASE（已换挡过）#{}", t.getId());
			return;
		}
		Double newSl = optFinite(d, "newSl");
		Double rangeLow = optFinite(d, "rangeLow");
		Double rangeHigh = optFinite(d, "rangeHigh");
		if (newSl == null || rangeLow == null || rangeHigh == null) {
			return;
		}
		boolean buy = "BUY".equals(t.getAction());
		double last;
		try {
			last = lastPrice(t.getSymbol());
		} catch (Exception e) {
			log.warn("REBASE 取价失败 #{}: {}", t.getId(), e.getMessage());
			return;
		}
		// 结构校验：当前价仍在高周期区间内（结构未破），新止损在区间失效位之外
		boolean structureIntact = last > rangeLow && last < rangeHigh;
		boolean slBeyondRange = buy ? newSl < rangeLow : newSl > rangeHigh;
		if (!structureIntact || !slBeyondRange) {
			log.info("拒绝 REBASE（结构校验不过）#{} last={} range=[{},{}] newSl={}",
					t.getId(), last, rangeLow, rangeHigh, newSl);
			return;
		}
		// 风险硬顶：浮亏 + 剩余风险 ≤ 2% 账户（账户风险 = 杠杆×保证金占比×距离）
		double entry = t.getActualEntry() != null ? t.getActualEntry() : t.getEntry();
		AiConfig cfg = configService.getConfig();
		double lev = Math.min(cfg.getLeverage() == null ? 100 : cfg.getLeverage(), 100);
		double marginPct = cfg.getAutoMarginPct() == null ? 5.0 : cfg.getAutoMarginPct();
		double floatLossPct = buy ? (entry - last) / entry * 100 : (last - entry) / entry * 100;
		if (floatLossPct < 0) {
			floatLossPct = 0; // 浮盈时只看剩余风险
		}
		double remainPct = buy ? (last - newSl) / last * 100 : (newSl - last) / last * 100;
		double totalRisk = (floatLossPct + remainPct) * lev * marginPct / 100.0;
		if (totalRisk > REBASE_MAX_RISK_PCT) {
			log.info("拒绝 REBASE（总风险 {}% > {}%）#{}",
					String.format(Locale.ROOT, "%.2f", totalRisk), REBASE_MAX_RISK_PCT, t.getId());
			return;
		}
		try {
			executor.setTradingStop(t.getSymbol(), t.getAction(), t.getTakeProfit(), newSl);
			t.setStopLoss(newSl);
			t.setRebasedAt(java.time.LocalDateTime.now());
			t.setNote("换挡扛单(majors): " + reason);
			repository.save(t);
			log.info("持仓管理 #{} {} REBASE: sl->{} 总风险{}%: {}",
					t.getId(), t.getSymbol(), newSl,
					String.format(Locale.ROOT, "%.2f", totalRisk), reason);
		} catch (Exception e) {
			log.warn("REBASE 设置失败 #{}: {}", t.getId(), e.getMessage());
		}
	}

	/** 提前离场：市价平仓，实际盈亏交给结算心跳从 closed-pnl 读取 */
	private void applyClose(AiAdviceTrack t, String reason) {
		try {
			var pos = executor.position(t.getSymbol());
			if (pos == null) {
				return; // 仓位已被 TP/SL 结清，交给结算心跳
			}
			executor.marketClose(t.getSymbol(), pos.getString("side"),
					Double.parseDouble(pos.getString("size")));
			t.setNote("动态管理离场: " + reason);
			repository.save(t);
			log.info("持仓管理 #{} {} 提前离场: {}", t.getId(), t.getSymbol(), reason);
		} catch (Exception e) {
			log.warn("提前离场失败 #{} {}: {}", t.getId(), t.getSymbol(), e.getMessage());
		}
	}

	/** 调整 TP/SL：只允许收紧（锁利润/提前落袋），禁止放宽风险 */
	private void applyMove(AiAdviceTrack t, JSONObject d, String reason) {
		boolean buy = "BUY".equals(t.getAction());
		Double newSl = optFinite(d, "newSl");
		Double newTp = optFinite(d, "newTp");
		if (newSl == null && newTp == null) {
			return;
		}
		// 收紧校验：SL 只能向有利方向移（BUY 上移 / SELL 下移），TP 只能靠近
		if (newSl != null) {
			boolean ok = buy ? newSl > t.getStopLoss() : newSl < t.getStopLoss();
			if (!ok) {
				log.info("拒绝放宽止损 #{}: {} -> {}", t.getId(), t.getStopLoss(), newSl);
				newSl = null;
			}
		}
		if (newTp != null) {
			boolean ok = buy ? newTp < t.getTakeProfit() : newTp > t.getTakeProfit();
			if (!ok) {
				log.info("拒绝放宽止盈 #{}: {} -> {}", t.getId(), t.getTakeProfit(), newTp);
				newTp = null;
			}
		}
		if (newSl == null && newTp == null) {
			return;
		}
		double sl = newSl != null ? newSl : t.getStopLoss();
		double tp = newTp != null ? newTp : t.getTakeProfit();
		try {
			executor.setTradingStop(t.getSymbol(), t.getAction(), tp, sl);
			if (newSl != null) {
				t.setStopLoss(newSl);
			}
			if (newTp != null) {
				t.setTakeProfit(newTp);
			}
			t.setNote("动态管理调整: " + reason);
			repository.save(t);
			log.info("持仓管理 #{} {} 调整 sl={} tp={}: {}", t.getId(), t.getSymbol(), sl, tp, reason);
		} catch (Exception e) {
			// 常见原因：新触发价距标记价过近被交易所拒绝
			log.warn("TP/SL 调整被拒 #{} {}: {}", t.getId(), t.getSymbol(), e.getMessage());
		}
	}

	// ==================== LLM 决策 ====================

	private JSONObject judge(AiConfig config, AiAdviceTrack t) throws Exception {
		double last = lastPrice(t.getSymbol());
		double entry = t.getActualEntry() != null ? t.getActualEntry() : t.getEntry();
		boolean buy = "BUY".equals(t.getAction());
		double unrealized = buy ? (last - entry) / entry * 100 : (entry - last) / entry * 100;
		double distTp = Math.abs(t.getTakeProfit() - last) / last * 100;
		double distSl = Math.abs(last - t.getStopLoss()) / last * 100;
		double[] mom = momentum(t.getSymbol());

		String modelJson = "";
		try {
			modelJson = toolRegistry.execute("get_model_prediction",
					new JSONObject().put("symbol", t.getSymbol()));
		} catch (Exception e) {
			log.debug("管理复查模型预测不可用 {}: {}", t.getSymbol(), e.getMessage());
		}

		String user = """
				品种：%s %s 数量:%s
				实际入场:%s 止损:%s 止盈:%s 现价:%s
				浮动盈亏:%.2f%%（1x价格口径） 距止盈:%.2f%% 距止损:%.2f%%
				近1分钟:%+.2f%% 近5分钟:%+.2f%% 近15分钟:%+.2f%%
				统计模型预测:%s
				请给出管理决策 JSON。""".formatted(t.getSymbol(), t.getAction(), t.getQty(),
				entry, t.getStopLoss(), t.getTakeProfit(), last,
				unrealized, distTp, distSl, mom[0], mom[1], mom[2],
				modelJson.isEmpty() ? "不可用" : modelJson);

		JSONObject body = new JSONObject()
				.put("model", config.getModel())
				.put("temperature", 0.1)
				.put("messages", new JSONArray()
						.put(new JSONObject().put("role", "system").put("content", SYSTEM_PROMPT))
						.put(new JSONObject().put("role", "user").put("content", user)));
		Request request = new Request.Builder()
				.url(config.getBaseUrl().replaceAll("/+$", "") + "/chat/completions")
				.header("Authorization", "Bearer " + config.getApiKey())
				.post(RequestBody.create(body.toString(),
						MediaType.parse("application/json; charset=utf-8")))
				.build();
		try (Response response = clients.obtain(ProxiedHttpClients.SLOW)
				.newCall(request).execute()) {
			String respBody = response.body() != null ? response.body().string() : "";
			if (!response.isSuccessful()) {
				throw new IllegalStateException("管理 LLM HTTP " + response.code()
						+ ": " + truncate(respBody, 120));
			}
			String content = new JSONObject(respBody).getJSONArray("choices")
					.getJSONObject(0).getJSONObject("message").optString("content", "");
			return parseLoose(content);
		}
	}

		private static final String SYSTEM_PROMPT = """
			你是持仓风控管理器，负责已开仓位的动态调整。决策原则（用户交易哲学）：
			- 默认 HOLD：入场逻辑未破坏就让利润跑，不折腾。没有明确理由不动仓。
			- CLOSE（提前离场）适用：
			  1) 浮盈中但动能衰竭（涨幅收窄/近几分钟转跌/接近止盈但反复不破），预计回吐利润；
			  2) 浮亏且将跌破关键结构位，等止损代价过大，主动小亏离场；
			  3) 统计模型明确转向反方向且与持仓方向冲突。
			- MOVE_SL：浮盈明显时上移止损到成本位或结构位锁定利润（BUY 只能上移，SELL 只能下移）。
			- MOVE_TP：动能衰竭且距止盈不远，止盈靠近提前落袋（BUY 只能下调，SELL 只能上调）。
			- REBASE（换挡扛单，仅 BTC/ETH/SOL 的浮亏单，山寨绝对禁止）：
			  这是你对 majors 浮亏单的重要且常用的处置，不是最后手段——
			  majors 历史数据：亏损多为震荡噪音（69%% 在 4h 内回到止盈），
			  被紧止损打掉再眼看价格回去是最大的利润泄漏。
			  触发画像（满足前两条即倾向 REBASE）：
			  1) 浮亏中（0.1%%~0.5%% 区间最典型）且近15分钟动能已收敛或转平（不再单边恶化）；
			  2) 价格仍在小时/日线区间内部（距区间边界有明显空间，结构未破）；
			  3) 统计模型方向未反转（仍支持持仓方向，或至少不强烈反向）。
			  做法：止损换到高周期区间失效位（边界之外），研判升格为波段持有；
			  同时给出 rangeLow/rangeHigh（你对高周期结构的判断）与 newSl。
			  若动能持续恶化且模型同时转反，选 CLOSE 而非 REBASE。
			- 硬性禁止：对山寨（非 BTC/ETH/SOL）放宽止损或 REBASE、任何品种加仓、翻转方向
			  （翻转由主研判负责，你只管退出、收紧与 majors 的换挡）。
			- 止损已很近（距现价<0.15%%）且浮亏时倾向让它自然执行，不抢先。
			- 只输出一个 JSON 对象：{"decision":"HOLD|CLOSE|MOVE_SL|MOVE_TP|REBASE",
			  "newSl":数字或null,"newTp":数字或null,"rangeLow":数字或null,"rangeHigh":数字或null,
			  "reason":"30字内理由"}
			""";

	// ==================== 数据 ====================

	/** [近1分钟%, 近5分钟%, 近15分钟%] */
	private double[] momentum(String symbol) throws Exception {
		String json = bybitService.getPublicRaw("/v5/market/kline",
				java.util.Map.of("category", "linear", "symbol", symbol, "interval", "1", "limit", "20"));
		JSONArray list = new JSONObject(json).getJSONObject("result").getJSONArray("list");
		double[] closes = new double[list.length()];
		for (int i = 0; i < list.length(); i++) {
			// Bybit 倒序：index0 最新
			closes[i] = Double.parseDouble(list.getJSONArray(i).getString(4));
		}
		double last = closes[0];
		double[] out = new double[3];
		int[] offsets = { 1, 5, 15 };
		for (int i = 0; i < offsets.length; i++) {
			int idx = Math.min(offsets[i], closes.length - 1);
			out[i] = (last / closes[idx] - 1) * 100;
		}
		return out;
	}

	private double lastPrice(String symbol) throws Exception {
		String json = bybitService.getPublicRaw("/v5/market/tickers",
				java.util.Map.of("category", "linear", "symbol", symbol));
		JSONArray list = new JSONObject(json).getJSONObject("result").getJSONArray("list");
		if (list.isEmpty()) {
			throw new IllegalStateException(symbol + " 无行情");
		}
		return Double.parseDouble(list.getJSONObject(0).getString("lastPrice"));
	}

	private static Double optFinite(JSONObject o, String key) {
		Double v = o.optDouble(key, Double.NaN);
		return v.isNaN() || v <= 0 ? null : v;
	}

	private static JSONObject parseLoose(String content) {
		String s = content == null ? "" : content.trim();
		int start = s.indexOf('{');
		int end = s.lastIndexOf('}');
		if (start >= 0 && end > start) {
			s = s.substring(start, end + 1);
		}
		return new JSONObject(s);
	}

	private static long epochMs(java.time.LocalDateTime time) {
		return time.atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli();
	}

	private static String truncate(String s, int max) {
		return s == null || s.length() <= max ? s : s.substring(0, max);
	}
}
