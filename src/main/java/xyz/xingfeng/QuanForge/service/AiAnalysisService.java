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
import xyz.xingfeng.QuanForge.client.ProxiedHttpClients;
import xyz.xingfeng.QuanForge.entity.AiAlert;
import xyz.xingfeng.QuanForge.entity.AiConfig;
import xyz.xingfeng.QuanForge.repository.AiAlertRepository;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * AI 自动盯盘服务：
 * <ol>
 *   <li>定时（按配置间隔）扫描盯盘品种的 15m K 线；</li>
 *   <li>本地异动检测（涨跌幅 / RSI 极值 / 快讯关键词命中），未触发不调模型省 token；</li>
 *   <li>异动触发时把「K 线摘要 + 技术指标 + 相关快讯」打包发给 OpenAI 兼容接口；</li>
 *   <li>模型输出结构化 JSON 告警，落库供前端展示；同品种冷却期内不重复告警。</li>
 * </ol>
 * 也提供手动分析入口（无视异动阈值直接分析）。
 */
@Service
public class AiAnalysisService {

	private static final Logger log = LoggerFactory.getLogger(AiAnalysisService.class);

	/** 快讯关键词（中英）：命中即视为潜在异动信号 */
	private static final String[] NEWS_KEYWORDS = {
			"暴跌", "暴涨", "崩盘", "闪崩", "爆仓", "清算", "黑客", "被盗", "攻击", "漏洞",
			"监管", "起诉", "封禁", "禁令", "罚款", "降息", "加息", "ETF", "减半", " halving",
			"surge", "plunge", "crash", "hack", "exploit", "regulat", "ban", "lawsuit",
			"SEC", "ETF", "liquidation", "rate cut", "rate hike", "approval", "approve"
	};

	/** 同品种告警冷却倍数：冷却 = 扫描间隔 × 该倍数 */
	private static final double COOLDOWN_FACTOR = 2.0;

	private final AiConfigService configService;
	private final BybitService bybitService;
	private final NewsService newsService;
	private final ProxiedHttpClients clients;
	private final AiAlertRepository alertRepository;
	private final AiAgentService agentService;
	private final AiAdviceTracker adviceTracker;

	/** 各品种上次告警时间（epoch millis） */
	private final Map<String, Long> lastAlertAt = new ConcurrentHashMap<>();

	/** 上次自动扫描时间 */
	private volatile long lastScanAt = 0;

	public AiAnalysisService(AiConfigService configService, BybitService bybitService,
			NewsService newsService, ProxiedHttpClients clients,
			AiAlertRepository alertRepository, AiAgentService agentService,
			AiAdviceTracker adviceTracker) {
		this.configService = configService;
		this.bybitService = bybitService;
		this.newsService = newsService;
		this.clients = clients;
		this.alertRepository = alertRepository;
		this.agentService = agentService;
		this.adviceTracker = adviceTracker;
	}

	/** 调度心跳：每 30 秒检查一次是否到达配置的扫描间隔 */
	@Scheduled(fixedDelay = 30_000, initialDelay = 20_000)
	public void tick() {
		AiConfig config = configService.getConfig();
		if (!Boolean.TRUE.equals(config.getEnabled()) || !configService.isConfigured()) {
			return;
		}
		long intervalMs = config.getScanIntervalMinutes() * 60_000L;
		if (System.currentTimeMillis() - lastScanAt < intervalMs) {
			return;
		}
		lastScanAt = System.currentTimeMillis();
		try {
			scanAll(config);
		} catch (Exception e) {
			log.warn("AI 盯盘扫描失败: {}", e.getMessage());
		}
	}

	/** 扫描全部盯盘品种 */
	private void scanAll(AiConfig config) {
		for (String symbol : configService.watchList(config)) {
			try {
				scanSymbol(config, symbol, false);
			} catch (Exception e) {
				log.warn("盯盘 {} 失败: {}", symbol, e.getMessage());
			}
		}
	}

	/**
	 * 扫描单个品种：无足够数据返回 skip；异动且冷却过期才调模型。
	 *
	 * @param manual true = 手动分析（无视阈值与冷却，直接调模型）
	 * @return 生成的告警；未触发或冷却中返回 null
	 */
	public AiAlert scanSymbol(AiConfig config, String symbol, boolean manual) throws Exception {
		double[][] klines = fetchKlines(symbol, "15", 100);
		double[] opens = klines[0];
		double[] highs = klines[1];
		double[] lows = klines[2];
		double[] closes = klines[3];
		if (closes.length < 30) {
			log.debug("{} K 线数据不足（{} 根），跳过", symbol, closes.length);
			return null;
		}

		double last = closes[closes.length - 1];
		double pct15m = pctChange(closes, 1);
		double pct1h = pctChange(closes, 4);
		double rsi = IndicatorMath.rsiLast(closes, 14);

		// ---- 本地异动检测 ----
		List<String> triggers = new ArrayList<>();
		double threshold = config.getChangeThresholdPct();
		if (Math.abs(pct15m) >= threshold) {
			triggers.add(String.format(Locale.ROOT, "15m 涨跌 %.2f%%", pct15m));
		}
		if (Math.abs(pct1h) >= threshold * 2) {
			triggers.add(String.format(Locale.ROOT, "1h 涨跌 %.2f%%", pct1h));
		}
		if (!Double.isNaN(rsi) && (rsi >= 75 || rsi <= 25)) {
			triggers.add(String.format(Locale.ROOT, "RSI14 %.1f", rsi));
		}
		addScalpingTriggers(config, symbol, triggers);
		List<NewsService.NewsItem> relatedNews = new ArrayList<>();
		if (Boolean.TRUE.equals(config.getNewsKeywordOn())) {
			for (NewsService.NewsItem item : newsService.latest(50, "all")) {
				if (System.currentTimeMillis() - item.publishedAt() > 45 * 60_000L) {
					continue;
				}
				if (hitKeyword(item.title()) || hitKeyword(item.content())) {
					relatedNews.add(item);
					if (relatedNews.size() >= 8) {
						break;
					}
				}
			}
			if (!relatedNews.isEmpty()) {
				triggers.add("快讯关键词命中 " + relatedNews.size() + " 条");
			}
		}

		if (!manual) {
			if (triggers.isEmpty()) {
				return null;
			}
			Long lastAt = lastAlertAt.get(symbol);
			long cooldown = (long) (config.getScanIntervalMinutes() * 60_000L * COOLDOWN_FACTOR);
			if (lastAt != null && System.currentTimeMillis() - lastAt < cooldown) {
				log.debug("{} 冷却期内，跳过告警", symbol);
				return null;
			}
		}

		// ---- 调模型：优先 agentic（AI 自主拉取数据），不支持时回退固定上下文 ----
		String triggerText = manual ? "MANUAL"
				: String.join("；", triggers);
		JSONObject result;
		try {
			result = agentService.judge(config, symbol, triggerText);
		} catch (AiAgentService.ToolsUnsupportedException e) {
			log.info("{} 所用模型不支持 function calling，回退固定上下文模式", symbol);
			double[] macd = IndicatorMath.macdLast(closes, 12, 26, 9);
			MarketSnapshot snapshot = new MarketSnapshot(symbol, last, pct15m, pct1h, rsi,
					IndicatorMath.smaLast(closes, 7), IndicatorMath.smaLast(closes, 25),
					IndicatorMath.smaLast(closes, 99), macd[0], macd[1], macd[2],
					opens, highs, lows, closes, relatedNews);
			result = callLlm(config, snapshot, triggerText);
		}

		String level = normalizeLevel(result.optString("alertLevel", AiAlert.LEVEL_INFO));
		// 模型判定无风险（NONE）则不产生告警
		if (!manual && "NONE".equals(level)) {
			return null;
		}
		String action = result.optString("action", "").trim().toUpperCase(Locale.ROOT);
		double[] advice = adviceTriple(result, action);
		AiAlert alert = new AiAlert();
		alert.setSymbol(symbol);
		alert.setLevel("NONE".equals(level) ? AiAlert.LEVEL_INFO : level);
		alert.setTitle(truncate(result.optString("title", symbol + " 异动"), 120));
		alert.setSummary(truncate(result.optString("summary", ""), 250));
		alert.setDetail(truncate(withAdviceLine(result, action, advice), 4000));
		alert.setTrigger(truncate(triggerText, 250));
		alert.setConfidence(clampConfidence(result.optInt("confidence", 50)));
		alert = alertRepository.save(alert);
		if (advice != null) {
			adviceTracker.track(alert, action, advice[0], advice[1], advice[2]);
		}
		lastAlertAt.put(symbol, System.currentTimeMillis());
		log.info("AI 告警已生成: {} [{}] {}", symbol, alert.getLevel(), alert.getTitle());
		return alert;
	}

	/**
	 * 从模型输出提取合法建议三元组 [entry, stopLoss, takeProfit]。
	 * 方向缺失、价位缺项或方向矛盾（BUY 不满足 sl&lt;entry&lt;tp）返回 null，
	 * 防止幻觉价位误导跟单与纸面跟踪。
	 */
	private double[] adviceTriple(JSONObject result, String action) {
		if (!action.equals("BUY") && !action.equals("SELL")) {
			return null;
		}
		Double entry = optFinite(result, "entry");
		Double sl = optFinite(result, "stopLoss");
		Double tp = optFinite(result, "takeProfit");
		if (entry == null || sl == null || tp == null || entry <= 0 || sl <= 0 || tp <= 0) {
			return null;
		}
		boolean sane = action.equals("BUY") ? (sl < entry && entry < tp)
				: (tp < entry && entry < sl);
		if (!sane) {
			log.info("建议价位不合法（{} entry={} sl={} tp={}），丢弃建议行", action, entry, sl, tp);
			return null;
		}
		return new double[] { entry, sl, tp };
	}

	/**
	 * 把模型输出的 action/entry/stopLoss/takeProfit 拼入 detail 首行（带价位合法性校验）。
	 * 校验不过（advice 为 null）则只保留原文。
	 */
	private String withAdviceLine(JSONObject result, String action, double[] advice) {
		String detail = result.optString("detail", "");
		if (advice == null) {
			return detail;
		}
		return "参考建议：" + action + " 入场 " + advice[0] + "｜止损 " + advice[1] + "｜止盈 "
				+ advice[2] + "（仅供参考，非投资建议）\n" + detail;
	}

	private Double optFinite(JSONObject obj, String key) {
		try {
			double v = obj.getDouble(key);
			return Double.isFinite(v) ? v : null;
		} catch (Exception e) {
			return null;
		}
	}

	// ==================== 手动分析 ====================

	/** 手动触发一次分析（前端按钮），返回告警（level 至少 INFO） */
	public AiAlert analyzeNow(String symbol) throws Exception {
		AiConfig config = configService.getConfig();
		if (!configService.isConfigured()) {
			throw new IllegalStateException("AI 未配置：请先在设置页填写 API Key");
		}
		return scanSymbol(config, symbol.toUpperCase(Locale.ROOT), true);
	}

	// ==================== LLM 调用 ====================

	/** 一次分析的市场快照（直接字段传参，避免中间序列化） */
	private record MarketSnapshot(String symbol, double last, double pct15m, double pct1h,
			double rsi, double ma7, double ma25, double ma99, double dif, double dea, double hist,
			double[] opens, double[] highs, double[] lows, double[] closes,
			List<NewsService.NewsItem> news) {
	}

	private JSONObject callLlm(AiConfig config, MarketSnapshot s, String trigger) throws Exception {
		String systemPrompt = """
				你是专业的加密货币合约交易风控分析师。根据用户提供的 K 线数据、技术指标与快讯，\
				输出客观、克制的短线研判。禁止给出"保证""必然"等绝对表述，不构成投资建议。
				只输出一个 JSON 对象，不要输出任何其他文字或代码块标记，格式：
				{"alertLevel":"INFO|WARN|CRITICAL|NONE","action":"BUY|SELL|HOLD","entry":数字或null,\
				"stopLoss":数字或null,"takeProfit":数字或null,"title":"不超过20字的标题",\
				"summary":"不超过60字的摘要","detail":"200字以内的分析：趋势判断、关键支撑阻力位、\
				指标含义、快讯影响、风险提示","confidence":0到100的整数}
				判定标准：NONE=数据无异常；INFO=轻度异动值得关注；WARN=明显异动短期波动风险大；\
				CRITICAL=极端行情或重大利空利好，需立即关注。

				""" + config.strategyPromptBlock();

		StringBuilder klinesSb = new StringBuilder();
		int from = Math.max(0, s.closes().length - 12);
		for (int i = from; i < s.closes().length; i++) {
			klinesSb.append(String.format(Locale.ROOT, "%n- O=%.2f H=%.2f L=%.2f C=%.2f",
					s.opens()[i], s.highs()[i], s.lows()[i], s.closes()[i]));
		}
		StringBuilder newsSb = new StringBuilder();
		for (NewsService.NewsItem item : s.news()) {
			newsSb.append(String.format("%n- [%s] %s", item.source(), item.title()));
		}
		if (newsSb.isEmpty()) {
			newsSb.append("（无相关快讯）");
		}

		String userPrompt = """
				品种：%s
				触发原因：%s
				当前价：%.2f
				15m 涨跌：%.2f%%，1h 涨跌：%.2f%%
				技术指标（15m 周期）：MA7=%.2f，MA25=%.2f，MA99=%.2f，RSI14=%.1f，MACD: DIF=%.4f DEA=%.4f 柱=%.4f
				近 12 根 15m K 线（时间序列）：%s
				近 45 分钟相关快讯：%s
				请输出 JSON 研判。""".formatted(s.symbol(), trigger, s.last(), s.pct15m(),
				s.pct1h(), s.ma7(), s.ma25(), s.ma99(), s.rsi(), s.dif(), s.dea(), s.hist(),
				klinesSb, newsSb);

		JSONObject body = new JSONObject()
				.put("model", config.getModel())
				.put("temperature", 0.2)
				.put("messages", new JSONArray()
						.put(new JSONObject().put("role", "system").put("content", systemPrompt))
						.put(new JSONObject().put("role", "user").put("content", userPrompt)));

		String url = config.getBaseUrl().replaceAll("/+$", "") + "/chat/completions";
		Request request = new Request.Builder().url(url)
				.header("Authorization", "Bearer " + config.getApiKey())
				.header("Content-Type", "application/json")
				.post(RequestBody.create(body.toString(),
						MediaType.parse("application/json; charset=utf-8")))
				.build();
		try (Response response = clients.obtain(ProxiedHttpClients.SLOW)
				.newCall(request).execute()) {
			String respBody = response.body() != null ? response.body().string() : "";
			if (!response.isSuccessful()) {
				throw new IllegalStateException("LLM 接口 HTTP " + response.code()
						+ ": " + truncate(respBody, 200));
			}
			JSONObject resp = new JSONObject(respBody);
			String content = resp.getJSONArray("choices").getJSONObject(0)
					.getJSONObject("message").getString("content");
			return parseJsonLoose(content);
		}
	}

	/** 容错解析模型输出：剥掉 ```json 代码块、截取首个 { 到末个 } */
	private JSONObject parseJsonLoose(String content) {
		String s = content.trim();
		int start = s.indexOf('{');
		int end = s.lastIndexOf('}');
		if (start >= 0 && end > start) {
			s = s.substring(start, end + 1);
		}
		return new JSONObject(s);
	}

	// ==================== 数据与指标（后端简版） ====================

	/**
	 * 剥头皮信号（5m 级别）：急涨急跌 / 波动放大 / 布林收窄。
	 * 对应用户策略——只在「大概率出现 ≥ 出手门槛的单向波动」时触发 AI 评估。
	 * 数据拉取失败不影响原有 15m 触发器。
	 */
	private void addScalpingTriggers(AiConfig config, String symbol, List<String> triggers) {
		double minMove = config.getMinMovePct() == null ? 0.1 : config.getMinMovePct();
		try {
			double[][] k5 = fetchKlines(symbol, "5", 100);
			double[] highs = k5[1];
			double[] lows = k5[2];
			double[] closes = k5[3];
			if (closes.length < 40) {
				return;
			}
			double last = closes[closes.length - 1];
			// 1) 急涨急跌：最新一根 5m 涨跌 ≥ max(0.3%, 3×出手门槛)
			double prev = closes[closes.length - 2];
			double pct5 = prev == 0 ? 0 : (last - prev) / prev * 100;
			double impulseGate = Math.max(0.3, minMove * 3);
			if (Math.abs(pct5) >= impulseGate) {
				triggers.add(String.format(Locale.ROOT, "5m 急%s %.2f%%", pct5 > 0 ? "涨" : "跌", pct5));
			}
			// 2) 波动放大：最新 5m 波幅 ≥ 1.8×ATR14（脉冲启动特征）
			double atr = IndicatorMath.atrLast(highs, lows, closes, 14);
			if (!Double.isNaN(atr) && atr > 0 && last > 0) {
				double rangePct = (highs[highs.length - 1] - lows[lows.length - 1]) / last * 100;
				double atrPct = atr / last * 100;
				if (rangePct >= atrPct * 1.8) {
					triggers.add(String.format(Locale.ROOT, "波动放大：5m 波幅 %.2f%% ≈ %.1f×ATR",
							rangePct, rangePct / atrPct));
				}
			}
			// 3) 布林收窄：带宽为近 60 根最低（变盘临近，方向交给 AI 判断）
			if (bollSqueeze(closes, 20, 60)) {
				triggers.add("布林带宽收窄至近60根最低（变盘临近）");
			}
		} catch (Exception e) {
			log.debug("{} 5m 数据拉取失败，跳过剥头皮信号: {}", symbol, e.getMessage());
		}
	}

	/** 布林带宽 (upper-lower)/mid，BOLL(20,2)；endExclusive 之前的 20 根窗口 */
	private double bollWidth(double[] closes, int endExclusive) {
		int period = 20;
		int from = endExclusive - period;
		if (from < 0) {
			return Double.NaN;
		}
		double sum = 0;
		for (int i = from; i < endExclusive; i++) {
			sum += closes[i];
		}
		double mid = sum / period;
		if (mid <= 0) {
			return Double.NaN;
		}
		double sq = 0;
		for (int i = from; i < endExclusive; i++) {
			sq += (closes[i] - mid) * (closes[i] - mid);
		}
		double sd = Math.sqrt(sq / period);
		return 4 * sd / mid;
	}

	/** 当前带宽是否为近 lookback 根最低（含当前根） */
	private boolean bollSqueeze(double[] closes, int period, int lookback) {
		double cur = bollWidth(closes, closes.length);
		if (Double.isNaN(cur)) {
			return false;
		}
		for (int end = Math.max(period, closes.length - lookback); end < closes.length; end++) {
			double w = bollWidth(closes, end);
			if (!Double.isNaN(w) && w < cur) {
				return false;
			}
		}
		return true;
	}

	/** 拉 K 线返回 [opens, highs, lows, closes]（Bybit 公开接口，无需凭证，时间升序） */
	private double[][] fetchKlines(String symbol, String interval, int limit) throws Exception {
		String json = bybitService.getPublicRaw("/v5/market/kline",
				Map.of("category", "linear", "symbol", symbol, "interval", interval, "limit",
						String.valueOf(limit)));
		JSONObject resp = new JSONObject(json);
		if (resp.getInt("retCode") != 0) {
			throw new IllegalStateException("Bybit kline: " + resp.getString("retMsg"));
		}
		JSONArray list = resp.getJSONObject("result").getJSONArray("list");
		List<double[]> rows = new ArrayList<>();
		for (int i = 0; i < list.length(); i++) {
			JSONArray k = list.getJSONArray(i);
			// Bybit 元素顺序 [start, open, high, low, close, volume]，原始按时间倒序
			rows.add(new double[] { Double.parseDouble(k.getString(1)),
					Double.parseDouble(k.getString(2)), Double.parseDouble(k.getString(3)),
					Double.parseDouble(k.getString(4)) });
		}
		java.util.Collections.reverse(rows); // 转时间升序
		double[] opens = new double[rows.size()];
		double[] highs = new double[rows.size()];
		double[] lows = new double[rows.size()];
		double[] closes = new double[rows.size()];
		for (int i = 0; i < rows.size(); i++) {
			double[] r = rows.get(i);
			opens[i] = r[0];
			highs[i] = r[1];
			lows[i] = r[2];
			closes[i] = r[3];
		}
		return new double[][] { opens, highs, lows, closes };
	}

	/** 近 n 根的涨跌幅（%）：n=1 即最后一根相对前一根 */
	private double pctChange(double[] closes, int n) {
		int len = closes.length;
		if (len <= n) {
			return 0;
		}
		double prev = closes[len - 1 - n];
		return prev == 0 ? 0 : (closes[len - 1] - prev) / prev * 100;
	}

	// ==================== 小工具 ====================

	private boolean hitKeyword(String text) {
		if (text == null || text.isEmpty()) {
			return false;
		}
		String lower = text.toLowerCase(Locale.ROOT);
		for (String kw : NEWS_KEYWORDS) {
			if (lower.contains(kw.trim().toLowerCase(Locale.ROOT))) {
				return true;
			}
		}
		return false;
	}

	private String normalizeLevel(String level) {
		if (level == null) {
			return AiAlert.LEVEL_INFO;
		}
		return switch (level.trim().toUpperCase(Locale.ROOT)) {
			case "WARN" -> AiAlert.LEVEL_WARN;
			case "CRITICAL" -> AiAlert.LEVEL_CRITICAL;
			case "NONE" -> "NONE";
			default -> AiAlert.LEVEL_INFO;
		};
	}

	private Integer clampConfidence(int c) {
		return Math.max(0, Math.min(100, c));
	}

	private String truncate(String s, int max) {
		if (s == null) {
			return "";
		}
		return s.length() <= max ? s : s.substring(0, max) + "…";
	}

	private double round2(double v) {
		return Double.isNaN(v) ? v : Math.round(v * 100) / 100.0;
	}

	private double round1(double v) {
		return Double.isNaN(v) ? v : Math.round(v * 10) / 10.0;
	}
}
