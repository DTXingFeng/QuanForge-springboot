package xyz.xingfeng.QuanForge.service;

import okhttp3.MediaType;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import org.json.JSONArray;
import org.json.JSONObject;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import xyz.xingfeng.QuanForge.client.ProxiedHttpClients;
import xyz.xingfeng.QuanForge.entity.AiAlert;
import xyz.xingfeng.QuanForge.repository.AiAlertRepository;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * AI 工具注册表：把行情/快讯/账户等信息接口包装成带 JSON Schema 描述的工具，
 * 供 agentic 循环中的 LLM 自主调用（function calling）。
 * <p>
 * 全部为只读工具——第一阶段 AI 不碰交易。工具执行器复用现有服务（走代理配置）。
 * 工具定义与 MCP tools 格式兼容，下轮包 MCP 协议时可直接复用。
 */
@Component
public class AiToolRegistry {

	private static final Logger log = LoggerFactory.getLogger(AiToolRegistry.class);

	/** K 线周期白名单（Bybit interval 参数） */
	private static final Set<String> INTERVALS = Set.of(
			"1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M");

	/** 单工具结果上限（字节），防超长结果撑爆上下文 */
	private static final int RESULT_MAX = 24_000;

	private final BybitService bybitService;
	private final NewsService newsService;
	private final AiAlertRepository alertRepository;
	private final ProxiedHttpClients clients;

	/** 模型推理 sidecar 地址（model_server.py，仅本机） */
	private final String modelServerUrl;

	/** 工具执行器表（注册顺序即暴露给模型的顺序） */
	private final Map<String, ToolExecutor> tools = new LinkedHashMap<>();

	/** 工具执行器：args 为模型给出的参数对象，返回 JSON 字符串 */
	@FunctionalInterface
	interface ToolExecutor {
		String execute(JSONObject args) throws Exception;
	}

	public AiToolRegistry(BybitService bybitService, NewsService newsService,
			AiAlertRepository alertRepository, ProxiedHttpClients clients,
			@Value("${app.model.server-url:http://127.0.0.1:40703}") String modelServerUrl) {
		this.bybitService = bybitService;
		this.newsService = newsService;
		this.alertRepository = alertRepository;
		this.clients = clients;
		this.modelServerUrl = modelServerUrl;
		registerAll();
	}

	private void registerAll() {
		// ---- 行情 ----
		register("get_ticker",
				"获取合约最新行情：最新价、24h 涨跌幅、高低价、成交额、资金费率。参数：symbol 如 BTCUSDT",
				obj().put("symbol", obj().put("type", "string").put("description", "交易对，如 BTCUSDT")),
				list("symbol"),
				args -> {
					String symbol = sym(args);
					JSONObject t = tickerRow(symbol);
					if (t == null) {
						return err(symbol + " 无行情数据");
					}
					return new JSONObject()
							.put("symbol", symbol)
							.put("lastPrice", num(t.optString("lastPrice")))
							.put("price24hPcnt", num(t.optString("price24hPcnt")))
							.put("highPrice24h", num(t.optString("highPrice24h")))
							.put("lowPrice24h", num(t.optString("lowPrice24h")))
							.put("turnover24h", num(t.optString("turnover24h")))
							.put("fundingRate", num(t.optString("fundingRate")))
							.toString();
				});

		register("get_kline",
				"获取 K 线（OHLCV）。interval: 1/5/15/30/60/240/D（分钟），limit ≤ 200。判断趋势与形态用。",
				obj()
						.put("symbol", obj().put("type", "string"))
						.put("interval", obj().put("type", "string").put("description", "默认 15"))
						.put("limit", obj().put("type", "integer").put("description", "默认 60，上限 200")),
				list("symbol"),
				args -> {
					String symbol = sym(args);
					String interval = args.optString("interval", "15");
					if (!INTERVALS.contains(interval)) {
						return err("interval 非法: " + interval);
					}
					int limit = clamp(args.optInt("limit", 60), 10, 200);
					JSONArray rows = rawKlines(symbol, interval, limit);
					JSONArray out = new JSONArray();
					for (int i = 0; i < rows.length(); i++) {
						JSONArray k = rows.getJSONArray(i);
						// [start, open, high, low, close, volume]（Bybit 原始倒序）
						out.put(new JSONArray()
								.put(Long.parseLong(k.getString(0)))
								.put(num(k.getString(1))).put(num(k.getString(2)))
								.put(num(k.getString(3))).put(num(k.getString(4)))
								.put(num(k.getString(5))));
					}
					return new JSONObject().put("symbol", symbol).put("interval", interval)
							.put("order", "时间倒序").put("count", out.length())
							.put("klines", out).toString();
				});

		register("get_indicators",
				"获取服务端计算的技术指标最新值（15m 等周期）：MA7/25/99、EMA7/25、BOLL(20,2)、RSI14、MACD(12,26,9)、KDJ(9,3,3)、ATR14。比自己用 K 线算更准更省。",
				obj()
						.put("symbol", obj().put("type", "string"))
						.put("interval", obj().put("type", "string").put("description", "默认 15")),
				list("symbol"),
				args -> {
					String symbol = sym(args);
					String interval = args.optString("interval", "15");
					double[][] khlc = klineArrays(symbol, interval, 150);
					if (khlc == null) {
						return err(symbol + " 无 K 线数据");
					}
					double[] highs = khlc[0];
					double[] lows = khlc[1];
					double[] closes = khlc[2];
					double[] macd = IndicatorMath.macdLast(closes, 12, 26, 9);
					double[] boll = IndicatorMath.bollLast(closes, 20, 2);
					double[] kdj = IndicatorMath.kdjLast(highs, lows, closes, 9, 3, 3);
					return new JSONObject()
							.put("symbol", symbol).put("interval", interval)
							.put("lastPrice", round(closes[closes.length - 1]))
							.put("MA7", round(IndicatorMath.smaLast(closes, 7)))
							.put("MA25", round(IndicatorMath.smaLast(closes, 25)))
							.put("MA99", round(IndicatorMath.smaLast(closes, 99)))
							.put("EMA7", round(IndicatorMath.emaLast(closes, 7)))
							.put("EMA25", round(IndicatorMath.emaLast(closes, 25)))
							.put("BOLL_upper", round(boll[0]))
							.put("BOLL_mid", round(boll[1]))
							.put("BOLL_lower", round(boll[2]))
							.put("RSI14", round(IndicatorMath.rsiLast(closes, 14)))
							.put("MACD_dif", round(macd[0]))
							.put("MACD_dea", round(macd[1]))
							.put("MACD_hist", round(macd[2]))
							.put("KDJ_K", round(kdj[0]))
							.put("KDJ_D", round(kdj[1]))
							.put("KDJ_J", round(kdj[2]))
							.put("ATR14", round(IndicatorMath.atrLast(highs, lows, closes, 14)))
							.toString();
				});

		register("get_orderbook",
				"获取盘口深度（买一卖一挂单量与价位分布）。评估短期支撑压力/扫盘风险用。",
				obj()
						.put("symbol", obj().put("type", "string"))
						.put("limit", obj().put("type", "integer").put("description", "档位数，默认 10，上限 25")),
				list("symbol"),
				args -> {
					String symbol = sym(args);
					int limit = clamp(args.optInt("limit", 10), 5, 25);
					String json = bybitService.getPublicRaw("/v5/market/orderbook",
							Map.of("category", "linear", "symbol", symbol, "limit", String.valueOf(limit)));
					JSONObject result = new JSONObject(json).getJSONObject("result");
					// Bybit V5 字段：b=买单 [价格,数量][]，a=卖单 [价格,数量][]
					JSONArray bids = result.getJSONArray("b");
					JSONArray asks = result.getJSONArray("a");
					return new JSONObject()
							.put("symbol", symbol)
							.put("bids", bids)
							.put("asks", asks)
							.put("bid1", bids.getJSONArray(0).getString(0))
							.put("ask1", asks.getJSONArray(0).getString(0))
							.toString();
				});

		register("get_funding_rate",
				"获取最新资金费率与下次结算时间。判断多空拥挤度与情绪。",
				obj().put("symbol", obj().put("type", "string")),
				list("symbol"),
				args -> {
					String symbol = sym(args);
					JSONObject t = tickerRow(symbol);
					if (t == null) {
						return err(symbol + " 无行情数据");
					}
					return new JSONObject()
							.put("symbol", symbol)
							.put("fundingRate", num(t.optString("fundingRate")))
							.put("nextFundingTime", t.optLong("nextFundingTime"))
							.toString();
				});

		register("get_instrument",
				"获取品种合约元数据：交易状态、最大可用杠杆、最小下单量、价格/数量步进、"
				+ "市价单上限。给出建议前必须查询——山寨币杠杆上限常低于 100（如 12.5/25/75），"
				+ "保证金盈亏换算必须用品种实际杠杆，而非用户画像里的惯用杠杆。",
				obj().put("symbol", obj().put("type", "string")),
				list("symbol"),
				args -> {
					String symbol = sym(args);
					String json = bybitService.getPublicRaw("/v5/market/instruments-info",
							Map.of("category", "linear", "symbol", symbol));
					JSONArray list = new JSONObject(json).getJSONObject("result")
							.getJSONArray("list");
					if (list.isEmpty()) {
						return err(symbol + " 无合约信息");
					}
					JSONObject i = list.getJSONObject(0);
					JSONObject lev = i.getJSONObject("leverageFilter");
					JSONObject lot = i.getJSONObject("lotSizeFilter");
					JSONObject price = i.getJSONObject("priceFilter");
					return new JSONObject()
							.put("symbol", symbol)
							.put("status", i.optString("status"))
							.put("maxLeverage", num(lev.optString("maxLeverage")))
							.put("minOrderQty", num(lot.optString("minOrderQty")))
							.put("qtyStep", num(lot.optString("qtyStep")))
							.put("maxMktOrderQty", num(lot.optString("maxMktOrderQty")))
							.put("tickSize", num(price.optString("tickSize")))
							.toString();
				});

		// ---- 统计模型 ----
		register("get_model_prediction",
				"统计模型（LightGBM，77万 1m K线样本训练）预测未来 30 分钟方向概率。"
				+ "返回 probUp（涨概率 0~1）与置信区间——模型输出按校准准确率分级使用："
				+ "|p-0.5|>=0.15 为高置信（回测 58% 准确），0.05~0.15 中置信（54%），"
				+ "<0.05 无参考价值应忽略。用于与你的定性判断交叉验证：与你的方向一致→confidence 上调；"
				+ "明显分歧→倾向 HOLD 并在 detail 说明分歧点。"
				+ "注意：模型仅用 BTC/ETH/SOL 训练，其他品种为分布外推断，参考意义降低。",
				obj().put("symbol", obj().put("type", "string")),
				list("symbol"),
				args -> {
					String symbol = sym(args);
					try {
						JSONArray rows = rawKlines(symbol, "1", 300);
						if (rows.length() < 130) {
							return err(symbol + " 1m K 线不足，无法预测");
						}
						JSONObject body = new JSONObject().put("klines", rows);
						Request req = new Request.Builder()
								.url(modelServerUrl + "/predict")
								.post(RequestBody.create(body.toString(),
										MediaType.parse("application/json; charset=utf-8")))
								.build();
						// model_server 在本机，ProxiedHttpClients 对 localhost 直连
						try (Response resp = clients.obtain().newCall(req).execute()) {
							String rb = resp.body() != null ? resp.body().string() : "";
							if (!resp.isSuccessful()) {
								return err("模型服务不可用(HTTP " + resp.code() + "): "
										+ rb.substring(0, Math.min(rb.length(), 120)));
							}
							JSONObject r = new JSONObject(rb);
							return new JSONObject()
									.put("symbol", symbol)
									.put("probUp", r.getDouble("probUp"))
									.put("direction", r.getString("direction"))
									.put("confidence", r.getDouble("confidence"))
									.put("zone", r.getString("zone"))
									.put("expectedAccuracy", r.opt("expectedAcc"))
									.put("note", "未来30分钟方向概率；高置信区回测58%/中54%/低区间忽略")
									.toString();
						}
					} catch (Exception e) {
						return err("模型预测失败: " + e.getMessage());
					}
				});

		// ---- 消息面 ----
		register("get_news",
				"搜索快讯（华尔街见闻/Binance公告/CoinDesk/Cointelegraph 聚合，近 1-2 小时为主）。可按关键词过滤，如 ETF、监管、暴跌。",
				obj()
						.put("keyword", obj().put("type", "string").put("description", "标题/内容包含的关键词，可选"))
						.put("limit", obj().put("type", "integer").put("description", "默认 15，上限 40")),
				List.of(),
				args -> {
					String keyword = args.optString("keyword", "").trim().toLowerCase(Locale.ROOT);
					int limit = clamp(args.optInt("limit", 15), 1, 40);
					JSONArray out = new JSONArray();
					for (NewsService.NewsItem item : newsService.latest(200, "all")) {
						if (!keyword.isEmpty()
								&& !(item.title().toLowerCase(Locale.ROOT).contains(keyword)
										|| item.content().toLowerCase(Locale.ROOT).contains(keyword))) {
							continue;
						}
						out.put(new JSONObject()
								.put("source", item.source())
								.put("title", item.title())
								.put("content", item.content())
								.put("publishedAt", item.publishedAt())
								.put("url", item.url()));
						if (out.length() >= limit) {
							break;
						}
					}
					return new JSONObject().put("count", out.length()).put("items", out).toString();
				});

		// ---- 自我校准 ----
		register("get_recent_judgments",
				"获取你自己（AI）最近的研判记录与结果，用于避免重复判断和自我校准。",
				obj()
						.put("symbol", obj().put("type", "string").put("description", "可选，按品种过滤"))
						.put("limit", obj().put("type", "integer").put("description", "默认 10，上限 20")),
				List.of(),
				args -> {
					String symbol = args.optString("symbol", "").trim().toUpperCase(Locale.ROOT);
					int limit = clamp(args.optInt("limit", 10), 1, 20);
					JSONArray out = new JSONArray();
					for (AiAlert a : alertRepository.findTop50ByOrderByCreatedAtDesc()) {
						if (!symbol.isEmpty() && !symbol.equals(a.getSymbol())) {
							continue;
						}
						out.put(new JSONObject()
								.put("symbol", a.getSymbol())
								.put("level", a.getLevel())
								.put("title", a.getTitle())
								.put("summary", a.getSummary())
								.put("trigger", a.getTrigger())
								.put("confidence", a.getConfidence())
								.put("createdAt", a.getCreatedAt().toString()));
						if (out.length() >= limit) {
							break;
						}
					}
					return new JSONObject().put("count", out.length()).put("items", out).toString();
				});

		// ---- 账户（只读）----
		register("get_positions",
				"查询当前合约持仓（只读）：品种、方向、数量、均价、未实现盈亏、杠杆、强平价、挂着的止盈止损。给出建议前先看，避免与现有仓位矛盾。",
				obj().put("name", obj().put("type", "string").put("description", "凭证标识，可省略")),
				List.of(),
				args -> getPositionsJson(args.optString("name", null)));

		register("get_wallet",
				"查询统一账户钱包（只读）：总权益、可用余额、USDT 余额。用于评估建议的仓位可行性。",
				obj().put("name", obj().put("type", "string").put("description", "凭证标识，可省略")),
				List.of(),
				args -> {
					String json = bybitService.getRaw(args.optString("name", null),
							"/v5/account/wallet-balance", Map.of("accountType", "UNIFIED"));
					JSONObject account = new JSONObject(json).getJSONObject("result")
							.getJSONArray("list").getJSONObject(0);
					JSONObject usdt = null;
					JSONArray coins = account.optJSONArray("coin");
					if (coins != null) {
						for (int i = 0; i < coins.length(); i++) {
							if ("USDT".equals(coins.getJSONObject(i).optString("coin"))) {
								usdt = coins.getJSONObject(i);
								break;
							}
						}
					}
					JSONObject out = new JSONObject()
							.put("totalEquity", num(account.optString("totalEquity")))
							.put("totalAvailableBalance", num(account.optString("totalAvailableBalance")))
							.put("totalWalletBalance", num(account.optString("totalWalletBalance")));
					if (usdt != null) {
						out.put("usdtWalletBalance", num(usdt.optString("walletBalance")))
								.put("usdtAvailableBalance", num(usdt.optString("availableBalance")));
					}
					return out.toString();
				});
	}

	// ==================== 对外接口 ====================

	/** OpenAI function calling 格式的工具定义（也兼容 MCP tools 结构） */
	public JSONArray toolsJson() {
		JSONArray out = new JSONArray();
		tools.forEach((name, executor) -> {
			ToolDef def = defs.get(name);
			out.put(new JSONObject()
					.put("type", "function")
					.put("function", new JSONObject()
							.put("name", name)
							.put("description", def.description())
							.put("parameters", def.parameters())));
		});
		return out;
	}

	/** 是否已注册该工具 */
	public boolean has(String name) {
		return tools.containsKey(name);
	}

	/** 执行工具；结果超长截断。异常返回 {"error": ...} 让模型自行调整。 */
	public String execute(String name, JSONObject args) {
		ToolExecutor executor = tools.get(name);
		if (executor == null) {
			return err("未知工具: " + name);
		}
		try {
			long start = System.currentTimeMillis();
			String result = executor.execute(args == null ? new JSONObject() : args);
			if (result.length() > RESULT_MAX) {
				result = result.substring(0, RESULT_MAX) + "…(截断)";
			}
			log.info("[AI工具] {} 耗时 {}ms 结果 {} 字节", name,
					System.currentTimeMillis() - start, result.length());
			return result;
		} catch (Exception e) {
			log.warn("[AI工具] {} 执行失败: {}", name, e.getMessage());
			return err(name + " 执行失败: " + e.getMessage());
		}
	}

	// ==================== 注册与工具实现辅助 ====================

	private record ToolDef(String name, String description, JSONObject parameters) {
	}

	private final Map<String, ToolDef> defs = new LinkedHashMap<>();

	private void register(String name, String description, JSONObject properties,
			List<String> required, ToolExecutor executor) {
		// OpenAI 工具 schema：属性必须包在 properties 层（Gemini 后端严格校验，裸字段会 400）
		JSONObject parameters = new JSONObject()
				.put("type", "object")
				.put("properties", properties)
				.put("required", new JSONArray(required));
		defs.put(name, new ToolDef(name, description, parameters));
		tools.put(name, executor);
	}

	/** tickers 行（linear） */
	private JSONObject tickerRow(String symbol) throws Exception {
		String json = bybitService.getPublicRaw("/v5/market/tickers",
				Map.of("category", "linear", "symbol", symbol));
		JSONArray list = new JSONObject(json).getJSONObject("result").getJSONArray("list");
		return list.isEmpty() ? null : list.getJSONObject(0);
	}

	/** 原始 K 线行（Bybit 倒序原样） */
	private JSONArray rawKlines(String symbol, String interval, int limit) throws Exception {
		String json = bybitService.getPublicRaw("/v5/market/kline",
				Map.of("category", "linear", "symbol", symbol,
						"interval", interval, "limit", String.valueOf(limit)));
		return new JSONObject(json).getJSONObject("result").getJSONArray("list");
	}

	/** K 线转数值数组（时间升序）：[highs, lows, closes] */
	private double[][] klineArrays(String symbol, String interval, int limit) {
		try {
			JSONArray rows = rawKlines(symbol, interval, limit);
			int n = rows.length();
			if (n == 0) {
				return null;
			}
			double[] highs = new double[n];
			double[] lows = new double[n];
			double[] closes = new double[n];
			for (int i = 0; i < n; i++) {
				JSONArray k = rows.getJSONArray(n - 1 - i); // 反转为升序
				highs[i] = Double.parseDouble(k.getString(2));
				lows[i] = Double.parseDouble(k.getString(3));
				closes[i] = Double.parseDouble(k.getString(4));
			}
			return new double[][] { highs, lows, closes };
		} catch (Exception e) {
			return null;
		}
	}

	private String getPositionsJson(String name) throws Exception {
		String json = bybitService.getRaw(name, "/v5/position/list",
				Map.of("category", "linear", "settleCoin", "USDT"));
		JSONArray list = new JSONObject(json).getJSONObject("result").getJSONArray("list");
		JSONArray out = new JSONArray();
		for (int i = 0; i < list.length(); i++) {
			JSONObject p = list.getJSONObject(i);
			String size = p.optString("size", "0");
			if ("0".equals(size) || size.isEmpty()) {
				continue;
			}
			out.put(new JSONObject()
					.put("symbol", p.optString("symbol"))
					.put("side", p.optString("side"))
					.put("size", num(size))
					.put("avgPrice", num(p.optString("avgPrice")))
					.put("leverage", p.optString("leverage"))
					.put("unrealisedPnl", num(p.optString("unrealisedPnl")))
					.put("liqPrice", p.optString("liqPrice"))
					.put("takeProfit", p.optString("takeProfit"))
					.put("stopLoss", p.optString("stopLoss")));
		}
		return new JSONObject().put("count", out.length()).put("positions", out).toString();
	}

	// ==================== 小工具 ====================

	private static JSONObject obj() {
		return new JSONObject();
	}

	private static List<String> list(String... items) {
		return List.of(items);
	}

	private static String sym(JSONObject args) {
		String s = args.optString("symbol", "").trim().toUpperCase(Locale.ROOT);
		if (s.isEmpty()) {
			throw new IllegalArgumentException("symbol 不能为空");
		}
		return s;
	}

	private static String err(String message) {
		return new JSONObject().put("error", message).toString();
	}

	private static double num(String s) {
		try {
			return Double.parseDouble(s);
		} catch (Exception e) {
			return 0;
		}
	}

	private static int clamp(int v, int min, int max) {
		return Math.max(min, Math.min(max, v));
	}

	private static double round(double v) {
		return Double.isNaN(v) ? Double.NaN : Math.round(v * 10000) / 10000.0;
	}
}
