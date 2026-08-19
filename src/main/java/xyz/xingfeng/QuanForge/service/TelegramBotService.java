package xyz.xingfeng.QuanForge.service;

import okhttp3.MediaType;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import org.json.JSONArray;
import org.json.JSONObject;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Lazy;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import xyz.xingfeng.QuanForge.client.ProxiedHttpClients;
import xyz.xingfeng.QuanForge.entity.AiAdviceTrack;
import xyz.xingfeng.QuanForge.entity.AiAlert;
import xyz.xingfeng.QuanForge.entity.AiConfig;
import xyz.xingfeng.QuanForge.entity.TelegramConfig;
import xyz.xingfeng.QuanForge.repository.AiAdviceTrackRepository;
import xyz.xingfeng.QuanForge.repository.AiAlertRepository;
import xyz.xingfeng.QuanForge.repository.TelegramConfigRepository;

import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * Telegram 机器人：长轮询接收指令 + 主动推送告警/结算。
 * <ul>
 *   <li>无需公网：getUpdates 长轮询主动拉取（25s 挂起），不开放任何入站端口</li>
 *   <li>白名单：chatId 未绑定时 /start 自动捕获绑定；此后仅响应该会话</li>
 *   <li>代理：TG API 直连不通，走「强制代理」档位（跟随代理配置但不看 useForAi 开关）</li>
 *   <li>注意：同一 token 只能有一个实例在轮询，本地 dev 与 Pi 生产勿同时启用</li>
 * </ul>
 */
@Service
public class TelegramBotService {

	private static final Logger log = LoggerFactory.getLogger(TelegramBotService.class);

	private static final String API = "https://api.telegram.org/bot";
	/** getUpdates 挂起秒数；OkHttp 读超时需大于它 */
	private static final int POLL_TIMEOUT_S = 25;

	/** 轮询位移（已处理的最后 update_id + 1） */
	private volatile long updateOffset = 0;

	/** 命令菜单是否已注册（每进程一次；token 更换后重启生效） */
	private volatile boolean commandsRegistered = false;

	/** 运行时静音（/mute 开 /unmute 关）：静音期间一切推送不发，指令照常响应 */
	private volatile boolean muted = false;

	/** 非关键告警的同品种推送冷却（毫秒）：20 分钟内同品种只推一条 */
	private final Map<String, Long> lastAlertPushAt = new java.util.concurrent.ConcurrentHashMap<>();

	/** 结算推送阈值（|resultPct|）：小于此幅度的琐碎结算不推（/tracks 可查） */
	private static final double SETTLE_PUSH_THRESHOLD = 0.3;

	private final TelegramConfigRepository repository;
	private final ProxiedHttpClients clients;
	private final AiConfigService aiConfigService;
	private final AiAnalysisService analysisService;
	private final AiAlertRepository alertRepository;
	private final AiAdviceTrackRepository trackRepository;
	private final BybitService bybitService;
	private final TradeAutopsyService autopsyService;

	public TelegramBotService(TelegramConfigRepository repository, ProxiedHttpClients clients,
			AiConfigService aiConfigService, @Lazy AiAnalysisService analysisService,
			AiAlertRepository alertRepository, AiAdviceTrackRepository trackRepository,
			BybitService bybitService, TradeAutopsyService autopsyService) {
		this.repository = repository;
		this.clients = clients;
		this.aiConfigService = aiConfigService;
		this.analysisService = analysisService;
		this.alertRepository = alertRepository;
		this.trackRepository = trackRepository;
		this.bybitService = bybitService;
		this.autopsyService = autopsyService;
	}

	// ==================== 轮询 ====================

	/** 长轮询心跳：未启用/未配置时秒回；409 冲突（多实例）只警告一次 */
	@Scheduled(fixedDelay = 2_000, initialDelay = 30_000)
	public void poll() {
		TelegramConfig config = getConfig();
		if (!Boolean.TRUE.equals(config.getEnabled()) || config.getBotToken().isBlank()) {
			return;
		}
		if (!commandsRegistered) {
			registerCommands(config.getBotToken());
		}
		try {
			String body = call(config.getBotToken(), "getUpdates",
					new JSONObject().put("offset", updateOffset).put("timeout", POLL_TIMEOUT_S)
							.put("allowed_updates", new JSONArray().put("message")),
					(POLL_TIMEOUT_S + 15) * 1000L);
			JSONArray updates = new JSONObject(body).getJSONArray("result");
			for (int i = 0; i < updates.length(); i++) {
				JSONObject update = updates.getJSONObject(i);
				updateOffset = Math.max(updateOffset, update.getLong("update_id") + 1);
				handleUpdate(config, update);
			}
		} catch (Exception e) {
			String msg = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
			// 409 = 另一实例在轮询同一 token；其余按网络问题降频
			log.warn("[TG] 轮询失败: {}", msg);
		}
	}

	private void handleUpdate(TelegramConfig config, JSONObject update) {
		JSONObject message = update.optJSONObject("message");
		if (message == null) {
			return;
		}
		String chatId = message.getJSONObject("chat").optString("id", "");
		String text = message.optString("text", "").trim();
		if (chatId.isEmpty() || text.isEmpty()) {
			return;
		}
		// 绑定逻辑：未绑定→首个 /start 的会话即主人；已绑定→白名单外一律忽略
		if (config.getChatId().isEmpty()) {
			if (text.equalsIgnoreCase("/start")) {
				bindChat(chatId);
			}
			return;
		}
		if (!chatId.equals(config.getChatId())) {
			log.warn("[TG] 白名单外会话 {} 尝试指令，已忽略", chatId);
			return;
		}
		dispatch(text);
	}

	@Transactional
	void bindChat(String chatId) {
		TelegramConfig config = getConfig();
		config.setChatId(chatId);
		repository.save(config);
		log.info("[TG] 会话已绑定: {}", chatId);
		send("已绑定 ✓ 这台工作站现在只听你的指令。\n\n" + helpText());
	}

	// ==================== 指令路由 ====================

	private void dispatch(String text) {
		String cmd = text.split("\\s+")[0].toLowerCase(Locale.ROOT).split("@")[0];
		String arg = text.contains(" ") ? text.substring(text.indexOf(' ') + 1).trim() : "";
		switch (cmd) {
			case "/start", "/help" -> send(helpText());
			case "/status" -> cmdStatus();
			case "/price" -> cmdPrice(arg);
			case "/analyze" -> cmdAnalyze(arg);
			case "/alerts" -> cmdAlerts();
			case "/tracks" -> cmdTracks();
			case "/positions" -> cmdPositions();
			case "/mute" -> {
				muted = true;
				send("已静音 🔇 推送暂停（指令仍可用），/unmute 恢复。");
			}
			case "/unmute" -> {
				muted = false;
				send("已恢复推送 🔔");
			}
			case "/autopsy" -> cmdAutopsy();
			default -> send("未知指令。/help 查看可用指令。");
		}
	}

	private String helpText() {
		return """
				QuanForge 工作站指令：
				/status — 服务状态（盯盘/战绩/钱包）
				/price BTCUSDT — 实时行情
				/analyze BTCUSDT — 触发一次 AI 研判（1-2 分钟后回推）
				/positions — 当前持仓
				/tracks — 跟踪战绩
				/alerts — 最近告警
				/autopsy — AI 验尸报告：最近交易的死因分析（30 秒）
				/mute /unmute — 静音/恢复推送
				（推送策略：有交易动作的建议 + 显著盈亏结算≥0.3%%）""";
	}

	/** /autopsy：验尸统计 + LLM 交易员语言解读 */
	private void cmdAutopsy() {
		send("验尸中…重放最近交易的 K 线（约 30 秒）");
		CompletableFuture.runAsync(() -> {
			try {
				var a = autopsyService.autopsyRecent(30);
				if (a.wins() + a.losses() == 0) {
					send("还没有已结算的交易，无从验尸。");
					return;
				}
				send(autopsyService.explain(a));
			} catch (Exception e) {
				send("验尸失败: " + e.getMessage());
			}
		});
	}

	private void cmdStatus() {
		AiConfig ai = aiConfigService.getConfig();
		StringBuilder sb = new StringBuilder("== 状态 ==\n");
		sb.append("自动盯盘: ").append(Boolean.TRUE.equals(ai.getEnabled()) ? "开" : "关");
		sb.append("（").append(ai.getWatchSymbols()).append("，每 ")
				.append(ai.getScanIntervalMinutes()).append(" 分钟）\n");
		sb.append("模型: ").append(ai.getModel()).append("\n");
		List<AiAdviceTrack> all = trackRepository.findAll();
		long wins = all.stream().filter(t -> AiAdviceTrack.STATUS_WIN.equals(t.getStatus())).count();
		long losses = all.stream().filter(t -> AiAdviceTrack.STATUS_LOSS.equals(t.getStatus())).count();
		long active = all.stream().filter(t -> AiAdviceTrack.STATUS_PENDING.equals(t.getStatus())
				|| AiAdviceTrack.STATUS_TRACKING.equals(t.getStatus())).count();
		long settled = wins + losses;
		sb.append("纸面战绩: ").append(settled == 0 ? "暂无已结算"
				: String.format(Locale.ROOT, "%d胜%d负 胜率%.0f%%（进行中%d）",
						wins, losses, wins * 100.0 / settled, active));
		sb.append("\n钱包: ").append(walletSummary());
		send(sb.toString());
	}

	private void cmdPrice(String symbol) {
		if (symbol.isEmpty()) {
			send("用法: /price BTCUSDT");
			return;
		}
		try {
			String json = bybitService.getPublicRaw("/v5/market/tickers",
					Map.of("category", "linear", "symbol", symbol.toUpperCase(Locale.ROOT)));
			JSONObject t = new JSONObject(json).getJSONObject("result").getJSONArray("list")
					.getJSONObject(0);
			send(String.format(Locale.ROOT, "%s  最新 %s\n24h %s%%  资金费率 %s%%",
					t.getString("symbol"), t.getString("lastPrice"),
					t.optString("price24hPcnt", "0"),
					t.optString("fundingRate", "0")));
		} catch (Exception e) {
			send("查询失败: " + e.getMessage());
		}
	}

	private void cmdAnalyze(String symbol) {
		if (symbol.isEmpty()) {
			send("用法: /analyze BTCUSDT");
			return;
		}
		String sym = symbol.toUpperCase(Locale.ROOT);
		send(sym + " 研判中…（AI 自主收集数据，1-2 分钟）");
		CompletableFuture.runAsync(() -> {
			try {
				AiAlert alert = analysisService.analyzeNow(sym);
				send(alert == null ? sym + " 数据不足，无法分析"
						: formatAlert(alert));
			} catch (Exception e) {
				send(sym + " 分析失败: " + e.getMessage());
			}
		});
	}

	private void cmdAlerts() {
		List<AiAlert> alerts = alertRepository.findTop50ByOrderByCreatedAtDesc();
		if (alerts.isEmpty()) {
			send("暂无告警");
			return;
		}
		StringBuilder sb = new StringBuilder("== 最近告警 ==\n");
		alerts.stream().limit(5).forEach(a -> sb.append(String.format(Locale.ROOT,
				"[%s] %s %s\n%s\n\n", a.getCreatedAt().toLocalTime(), a.getSymbol(),
				a.getLevel(), a.getTitle())));
		send(sb.toString());
	}

	private void cmdTracks() {
		List<AiAdviceTrack> tracks = trackRepository.findTop50ByOrderByCreatedAtDesc();
		if (tracks.isEmpty()) {
			send("暂无跟踪记录");
			return;
		}
		StringBuilder sb = new StringBuilder("== 纸面跟踪 ==\n");
		tracks.stream().limit(8).forEach(t -> sb.append(String.format(Locale.ROOT,
				"%s %s %s @%.6g → %s%s\n",
				t.getCreatedAt().toLocalTime(), t.getAction(), t.getSymbol(), t.getEntry(),
				statusLabel(t.getStatus()),
				t.getResultPct() == null ? "" : String.format(Locale.ROOT, " %+.2f%%", t.getResultPct()))));
		send(sb.toString());
	}

	private String statusLabel(String status) {
		return switch (status) {
			case "WIN" -> "✅盈";
			case "LOSS" -> "❌损";
			case "TRACKING" -> "⏳持仓";
			case "PENDING" -> "⏳等入场";
			default -> "◦过期";
		};
	}

	private void cmdPositions() {
		try {
			String json = bybitService.getRaw(null, "/v5/position/list",
					Map.of("category", "linear", "settleCoin", "USDT"));
			JSONArray list = new JSONObject(json).getJSONObject("result").getJSONArray("list");
			StringBuilder sb = new StringBuilder("== 持仓 ==\n");
			boolean any = false;
			for (int i = 0; i < list.length(); i++) {
				JSONObject p = list.getJSONObject(i);
				if (p.optDouble("size", 0) <= 0) {
					continue;
				}
				any = true;
				sb.append(String.format(Locale.ROOT, "%s %s %s 张 @%s\n浮盈亏 %s USDT｜强平 %s\n\n",
						p.getString("symbol"), p.getString("side"), p.getString("size"),
						p.getString("avgPrice"), p.optString("unrealisedPnl"),
						p.optString("liqPrice")));
			}
			send(any ? sb.toString() : "空仓");
		} catch (Exception e) {
			send("查询失败: " + e.getMessage());
		}
	}

	private String walletSummary() {
		try {
			String json = bybitService.getUnifiedWalletBalance();
			JSONObject account = new JSONObject(json).getJSONObject("result").getJSONArray("list")
					.getJSONObject(0);
			return account.optDouble("totalEquity", 0) + " USDT";
		} catch (Exception e) {
			return "读取失败";
		}
	}

	// ==================== 推送（供其他服务调用） ====================

	/**
	 * AI 告警推送（降噪策略）：
	 * <ul>
	 *   <li>只推"有交易动作"的建议（detail 带参考建议行）或 CRITICAL 级告警；
	 *       HOLD/观望类告警只进界面，不推</li>
	 *   <li>非 CRITICAL 同品种 20 分钟冷却，防止连环刷屏</li>
	 * </ul>
	 */
	public void notifyAlert(AiAlert alert) {
		if (!isReady() || muted) {
			return;
		}
		boolean critical = AiAlert.LEVEL_CRITICAL.equals(alert.getLevel());
		boolean actionable = alert.getDetail() != null && alert.getDetail().startsWith("参考建议");
		if (!critical && !actionable) {
			return;
		}
		if (!critical) {
			Long last = lastAlertPushAt.get(alert.getSymbol());
			long now = System.currentTimeMillis();
			if (last != null && now - last < 20 * 60_000L) {
				return;
			}
			lastAlertPushAt.put(alert.getSymbol(), now);
		}
		send(formatAlert(alert));
	}

	/** 跟踪结算推送：显著盈亏（|pct|≥0.3%）才推；琐碎结算 /tracks 可查 */
	public void notifySettle(AiAdviceTrack t) {
		if (!isReady() || muted) {
			return;
		}
		double pct = t.getResultPct() == null ? 0 : t.getResultPct();
		if (Math.abs(pct) < SETTLE_PUSH_THRESHOLD) {
			return;
		}
		send(String.format(Locale.ROOT, "%s %s %s @%.6g → %s（%+.2f%%）",
				t.getSymbol(), t.getAction(), t.getCreatedAt().toLocalTime(), t.getEntry(),
				statusLabel(t.getStatus()), pct));
	}

	private String formatAlert(AiAlert a) {
		String advice = a.getDetail().startsWith("参考建议")
				? "\n" + a.getDetail().split("\n")[0]
				: "";
		return String.format(Locale.ROOT, "🤖 [%s] %s %s\n%s%s\n（%s，置信度 %d%%）",
				a.getLevel(), a.getSymbol(), a.getTitle(), a.getSummary(), advice,
				a.getCreatedAt().toLocalTime(), a.getConfidence());
	}

	// ==================== 基础设施 ====================

	/** 注册命令菜单（聊天框 "/" 快捷列表），每进程一次 */
	private void registerCommands(String token) {
		try {
			JSONArray cmds = new JSONArray()
					.put(new JSONObject().put("command", "status").put("description", "服务状态：盯盘/战绩/钱包"))
					.put(new JSONObject().put("command", "price").put("description", "实时行情，如 /price BTCUSDT"))
					.put(new JSONObject().put("command", "analyze").put("description", "触发一次 AI 研判，如 /analyze ETHUSDT"))
					.put(new JSONObject().put("command", "positions").put("description", "当前持仓"))
					.put(new JSONObject().put("command", "tracks").put("description", "跟踪战绩"))
					.put(new JSONObject().put("command", "autopsy").put("description", "AI 验尸报告：交易死因分析"))
					.put(new JSONObject().put("command", "alerts").put("description", "最近告警"))
					.put(new JSONObject().put("command", "mute").put("description", "静音推送"))
					.put(new JSONObject().put("command", "unmute").put("description", "恢复推送"))
					.put(new JSONObject().put("command", "help").put("description", "指令帮助"));
			call(token, "setMyCommands", new JSONObject().put("commands", cmds), 15_000);
			commandsRegistered = true;
			log.info("[TG] 命令菜单已注册");
		} catch (Exception e) {
			log.warn("[TG] 命令菜单注册失败: {}", e.getMessage());
		}
	}

	private boolean isReady() {
		TelegramConfig c = getConfig();
		return Boolean.TRUE.equals(c.getEnabled()) && !c.getBotToken().isBlank()
				&& !c.getChatId().isBlank();
	}

	/** 发送消息（失败只记日志，绝不影响主流程） */
	public void send(String text) {
		TelegramConfig config = getConfig();
		if (config.getBotToken().isBlank() || config.getChatId().isBlank()) {
			return;
		}
		try {
			call(config.getBotToken(), "sendMessage",
					new JSONObject().put("chat_id", config.getChatId())
							.put("text", text.length() > 3500 ? text.substring(0, 3500) + "…" : text),
					20_000);
		} catch (Exception e) {
			log.warn("[TG] 发送失败: {}", e.getMessage());
		}
	}

	/** 统一 TG API 调用（GET 查询型 / POST 消息型合并为 POST JSON） */
	private String call(String token, String method, JSONObject payload, long readTimeoutMs)
			throws Exception {
		Request request = new Request.Builder()
				.url(API + token + "/" + method)
				.post(RequestBody.create(payload.toString(),
						MediaType.parse("application/json; charset=utf-8")))
				.build();
		try (Response response = clients.obtainAlwaysProxied(readTimeoutMs)
				.newCall(request).execute()) {
			String body = response.body() != null ? response.body().string() : "";
			if (!response.isSuccessful()) {
				throw new IllegalStateException("TG HTTP " + response.code() + ": "
						+ body.substring(0, Math.min(body.length(), 200)));
			}
			return body;
		}
	}

	@Transactional
	public TelegramConfig getConfig() {
		return repository.findById(TelegramConfig.SINGLETON_ID).orElseGet(() -> {
			TelegramConfig config = new TelegramConfig();
			config.setId(TelegramConfig.SINGLETON_ID);
			return repository.save(config);
		});
	}

	@Transactional
	public TelegramConfig save(String botToken, String chatId, Boolean enabled) {
		TelegramConfig config = getConfig();
		if (botToken != null && !botToken.isBlank()) {
			config.setBotToken(botToken.trim());
			commandsRegistered = false; // 新 token 需重新注册命令菜单
		}
		if (chatId != null) {
			config.setChatId(chatId.trim());
		}
		if (enabled != null) {
			config.setEnabled(enabled);
		}
		return repository.save(config);
	}
}
