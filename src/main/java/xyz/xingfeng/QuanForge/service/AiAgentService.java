package xyz.xingfeng.QuanForge.service;

import okhttp3.MediaType;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import org.json.JSONArray;
import org.json.JSONObject;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import xyz.xingfeng.QuanForge.client.ProxiedHttpClients;
import xyz.xingfeng.QuanForge.entity.AiConfig;

import java.util.Locale;

/**
 * AI Agentic 循环：把工具清单交给模型，模型自主决定拉取哪些数据，
 * 后端执行工具调用并回填结果，直到模型给出最终结构化研判。
 * <ul>
 *   <li>护栏：最多 {@link #MAX_ROUNDS} 轮工具调用；超限后强制要求直接输出结论</li>
 *   <li>降级：模型/服务商不支持 function calling（HTTP 400）时抛
 *       {@link ToolsUnsupportedException}，由调用方回退固定上下文模式</li>
 * </ul>
 */
@Service
public class AiAgentService {

	private static final Logger log = LoggerFactory.getLogger(AiAgentService.class);

	/** 最大工具调用轮数（成本护栏） */
	private static final int MAX_ROUNDS = 6;

	private final AiToolRegistry toolRegistry;
	private final ProxiedHttpClients clients;

	public AiAgentService(AiToolRegistry toolRegistry, ProxiedHttpClients clients) {
		this.toolRegistry = toolRegistry;
		this.clients = clients;
	}

	/** 服务商不支持 function calling，调用方应回退固定上下文模式 */
	static class ToolsUnsupportedException extends RuntimeException {
		ToolsUnsupportedException(String message) {
			super(message);
		}
	}

	/**
	 * 运行 agentic 研判：模型自主调用工具收集信息后输出最终 JSON。
	 *
	 * @param config  AI 配置（baseUrl/key/model）
	 * @param symbol  品种
	 * @param trigger 触发原因（异动描述或 MANUAL）
	 * @return 模型最终输出的 JSON 对象（结构见 system prompt）
	 */
	public JSONObject judge(AiConfig config, String symbol, String trigger) throws Exception {
		return judge(config, symbol, trigger, false);
	}

	/**
	 * 运行 agentic 研判：模型自主调用工具收集信息后输出最终 JSON。
	 *
	 * @param urgent true = 实时急动触发：提示词强调时效（价格在跑，结论要快），
	 *               工具轮数收紧到 3（少拉数据快出结论）
	 */
	public JSONObject judge(AiConfig config, String symbol, String trigger, boolean urgent)
			throws Exception {
		String urgencyHint = urgent ? """

				⚠ 时效警告：本次由实时行情急动触发，价格正在快速变动。
				- 你最多 3 轮工具调用（行情指标+模型预测即可，可省略消息面）
				- 每多犹豫 30 秒，入场价就离你看到的价位更远
				- 你的 entry 应基于最新价给出可立即成交的价位（不是等回调的理想价位），
				  破位追势场景 entry 可略高于现价（BUY）/低于现价（SELL）
				""" : "";
		JSONArray messages = new JSONArray()
				.put(new JSONObject().put("role", "system").put("content", systemPrompt(config)))
				.put(new JSONObject().put("role", "user").put("content",
						"""
								品种：%s
								触发原因：%s
								当前时间：%s
								请自主调用工具收集你判断所需的数据（建议：先行情指标，后消息面与持仓），\
								数据充分后直接输出最终 JSON 研判。%s""".formatted(symbol, trigger,
								java.time.LocalDateTime.now().withNano(0), urgencyHint)));

		JSONObject tools = new JSONObject()
				.put("tools", toolRegistry.toolsJson())
				.put("tool_choice", "auto");

		int maxRounds = urgent ? 3 : MAX_ROUNDS;
		for (int round = 1; round <= maxRounds; round++) {
			JSONObject message = chat(config, messages, tools);
			JSONArray toolCalls = message.optJSONArray("tool_calls");
			if (toolCalls == null || toolCalls.isEmpty()) {
				return parseJsonLoose(message.optString("content", ""));
			}
			// 回填 assistant 的工具调用意图（含 tool_calls 原样入历史）
			messages.put(message);
			for (int i = 0; i < toolCalls.length(); i++) {
				JSONObject call = toolCalls.getJSONObject(i);
				String id = call.optString("id", "call_" + round + "_" + i);
				String name = call.getJSONObject("function").optString("name", "");
				String argsRaw = call.getJSONObject("function").optString("arguments", "{}");
				if (!toolRegistry.has(name)) {
					messages.put(new JSONObject().put("role", "tool").put("tool_call_id", id)
							.put("content", "{\"error\":\"未知工具: " + name + "\"}"));
					continue;
				}
				JSONObject args;
				try {
					args = new JSONObject(argsRaw.isEmpty() ? "{}" : argsRaw);
				} catch (Exception e) {
					args = new JSONObject();
				}
				String result = toolRegistry.execute(name, args);
				log.info("[AI Agent] 第{}轮 工具 {} -> {} 字节", round, name, result.length());
				messages.put(new JSONObject().put("role", "tool").put("tool_call_id", id)
						.put("content", result));
			}
		}
		// 轮数用尽：去掉工具强制收敛
		log.info("[AI Agent] 工具轮数达上限，强制输出结论");
		messages.put(new JSONObject().put("role", "user")
				.put("content", "请停止调用工具，基于已获取的数据直接输出最终 JSON 研判。"));
		JSONObject message = chat(config, messages, new JSONObject());
		return parseJsonLoose(message.optString("content", ""));
	}

	// ==================== LLM 调用 ====================

	private JSONObject chat(AiConfig config, JSONArray messages, JSONObject extra)
			throws Exception {
		JSONObject body = new JSONObject()
				.put("model", config.getModel())
				.put("temperature", 0.2)
				.put("messages", messages);
		extra.keySet().forEach(k -> body.put(k, extra.get(k)));
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
				// 记录原始错误体，便于区分「不支持 tools」与真实错误（限流/配额/参数等）
				log.warn("[AI Agent] LLM HTTP {}: {}", response.code(), truncate(respBody, 400));
				if (response.code() == 400 && extra.has("tools")
						&& looksLikeToolsUnsupported(respBody)) {
					throw new ToolsUnsupportedException("服务商不支持 function calling: "
							+ truncate(respBody, 160));
				}
				throw new IllegalStateException("LLM 接口 HTTP " + response.code()
						+ ": " + truncate(respBody, 200));
			}
			return new JSONObject(respBody).getJSONArray("choices").getJSONObject(0)
					.getJSONObject("message");
		}
	}

	/**
	 * 严格判定：仅当错误体明确指向 tools/function 能力缺失才视为不支持。
	 * 之前版本匹配任何含 "tool"/"function"/"invalid parameter" 的 400，会把限流、
	 * 配额、参数等真实错误误判为不支持并静默降级。
	 */
	private boolean looksLikeToolsUnsupported(String body) {
		String lower = body.toLowerCase(Locale.ROOT);
		boolean capabilityError = lower.contains("does not support")
				|| lower.contains("not supported")
				|| lower.contains("unsupported")
				|| lower.contains("tool_use")
				|| lower.contains("parallel function");
		boolean mentionsTools = lower.contains("tool") || lower.contains("function");
		return capabilityError && mentionsTools;
	}

	/** 容错解析模型输出：剥掉 ```json 代码块、截取首个 { 到末个 } */
	private JSONObject parseJsonLoose(String content) {
		String s = content == null ? "" : content.trim();
		int start = s.indexOf('{');
		int end = s.lastIndexOf('}');
		if (start >= 0 && end > start) {
			s = s.substring(start, end + 1);
		}
		return new JSONObject(s);
	}

	private String truncate(String s, int max) {
		return s == null || s.length() <= max ? s : s.substring(0, max);
	}

	private String systemPrompt(AiConfig config) {
		return """
				你是专业的加密货币合约交易风控分析师，接入了一套实时数据工具。\
			 根据触发原因，自主调用工具获取你判断所需的数据（K线、技术指标、盘口、资金费率、快讯、\
			 历史判断、当前持仓），数据充分后输出最终研判。
			 规则：
			 - 工具调用要节制，通常 3-5 次足够：先行情指标（get_indicators/get_kline，\
			 剥头皮场景优先 1m/5m 周期），再调 get_model_prediction 获取统计模型方向参考，\
			 需要时再看消息面（get_news）与持仓（get_positions）。
			 - 给出 BUY/SELL 前必须完成三项检查（缺一不可）：\
			 ① get_model_prediction 拿到本品种统计模型方向与概率；\
			 ② get_positions 查持仓防矛盾；③ get_instrument 查杠杆上限算仓位。\
			 没调 get_model_prediction 就输出 BUY/SELL 属于违规操作。
			 - 模型交叉验证（结论必须体现在 detail 里）：\
			 模型方向与你一致→detail 写明"模型共振"及概率，confidence 上调 5~10；\
			 明显分歧→倾向 HOLD 并在 detail 说明分歧原因；低置信区(zone=low)的模型输出忽略。\
			 BUY/SELL 的 detail 里不含模型结论（共振/分歧）视为违规。
			 - 山寨币趋势纪律（BTC/ETH/SOL 之外的所有品种）：\
			 只顺 15m/1h 主趋势方向交易——趋势明确时只做顺势单，禁止逆势抄底/摸顶\
			 （历史验尸：山寨亏损的大头是逆势单，且亏损持续放大无法兜底）；\
			 15m/1h 趋势方向不明（震荡）时该品种输出 HOLD，不出手。\
			 majors 不受此限（双向皆可，震荡噪音由 REBASE 与止损管理兜底）。
			 - 不构成投资建议，禁止"保证""必然"等绝对表述。
			 - 最终只输出一个 JSON 对象（无其他文字/代码块标记），格式：
			 {"alertLevel":"INFO|WARN|CRITICAL|NONE","action":"BUY|SELL|HOLD","entry":数字或null,\
			 "stopLoss":数字或null,"takeProfit":数字或null,"title":"不超过20字",\
			 "summary":"不超过60字","detail":"200字内：趋势/支撑阻力/指标/消息面/风险","confidence":0到100整数}
			 - 判定：NONE=无异常；INFO=轻度异动；WARN=明显异动；CRITICAL=极端行情或重大消息。
			 - action=HOLD 时 entry/stopLoss/takeProfit 为 null。BUY 要求 stopLoss < entry < takeProfit，\
			 SELL 相反。价位必须基于工具获取的真实数据，禁止编造。

			 """ + config.strategyPromptBlock();
	}
}
