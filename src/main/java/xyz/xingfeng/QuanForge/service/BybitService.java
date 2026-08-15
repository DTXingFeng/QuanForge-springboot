package xyz.xingfeng.QuanForge.service;

import org.json.JSONArray;
import org.json.JSONObject;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;
import xyz.xingfeng.QuanForge.client.BybitGetClient;
import xyz.xingfeng.QuanForge.client.BybitPostClient;
import xyz.xingfeng.QuanForge.dto.CancelAllRequest;
import xyz.xingfeng.QuanForge.dto.CancelOrderRequest;
import xyz.xingfeng.QuanForge.dto.CreateOrderRequest;
import xyz.xingfeng.QuanForge.dto.DemoApplyMoneyRequest;
import xyz.xingfeng.QuanForge.dto.SetLeverageRequest;
import xyz.xingfeng.QuanForge.dto.TradingStopRequest;
import xyz.xingfeng.QuanForge.entity.ApiCredential;
import xyz.xingfeng.QuanForge.exception.NotFoundException;

import java.util.Map;

/**
 * Bybit 业务服务：封装对 Bybit V5 接口的调用。
 * 调用所需的 apiKey/apiSecret 从凭证表按标识读取（已落库为密文，读取即解密还原）。
 */
@Service
public class BybitService {

	/** 统一账户钱包余额接口路径 */
	private static final String WALLET_BALANCE_ENDPOINT = "/v5/account/wallet-balance";

	/** 虚拟盘申请/调整模拟资金接口路径 */
	private static final String DEMO_APPLY_MONEY_ENDPOINT = "/v5/account/demo-apply-money";

	/** 创建委托单接口路径 */
	private static final String CREATE_ORDER_ENDPOINT = "/v5/order/create";

	/** 设置杠杆接口路径 */
	private static final String SET_LEVERAGE_ENDPOINT = "/v5/position/set-leverage";

	/** 设置止盈止损接口路径 */
	private static final String TRADING_STOP_ENDPOINT = "/v5/position/trading-stop";

	/** 撤销委托单接口路径 */
	private static final String CANCEL_ORDER_ENDPOINT = "/v5/order/cancel";

	/** 撤销所有订单接口路径 */
	private static final String CANCEL_ALL_ENDPOINT = "/v5/order/cancel-all";

	/** 默认凭证标识 */
	public static final String DEFAULT_CREDENTIAL_NAME = "bybit";

	private static final Logger log = LoggerFactory.getLogger(BybitService.class);

	private final BybitGetClient getClient;
	private final BybitPostClient postClient;
	private final ApiCredentialService apiCredentialService;
	/** Jackson3，用于把 DTO 序列化为 Bybit 请求体（经 NON_NULL 注解自动省略空字段） */
	private final ObjectMapper objectMapper;

	public BybitService(BybitGetClient getClient, BybitPostClient postClient,
			ApiCredentialService apiCredentialService, ObjectMapper objectMapper) {
		this.getClient = getClient;
		this.postClient = postClient;
		this.apiCredentialService = apiCredentialService;
		this.objectMapper = objectMapper;
	}

	/** 查询统一账户钱包余额（使用默认 bybit 凭证，当前运行模式地址） */
	public String getUnifiedWalletBalance() {
		return getUnifiedWalletBalance(DEFAULT_CREDENTIAL_NAME);
	}

	/** 查询统一账户钱包余额（按凭证标识读取 apiKey/apiSecret，accountType=UNIFIED） */
	public String getUnifiedWalletBalance(String credentialName) {
		ApiCredential credential = resolveCredential(credentialName);
		try {
			return getClient.get(
					credential.getApiKey(),
					credential.getApiSecret(),
					WALLET_BALANCE_ENDPOINT,
					Map.of("accountType", "UNIFIED"));
		} catch (Exception e) {
			// 网络或签名异常统一包装，便于上层处理
			throw new RuntimeException("调用 Bybit 钱包余额失败: " + e.getMessage(), e);
		}
	}

	/**
	 * 发起 Bybit V5 POST 请求（按凭证标识读取 apiKey/apiSecret，签名串使用请求体原文）。
	 * <p>
	 * POST 签名串 = {@code timestamp + apiKey + recvWindow + rawRequestBody}，
	 * 与 GET 的参数排序签名不同，故走独立的 POST 客户端。
	 *
	 * @param credentialName 凭证标识（找不到抛 NotFoundException）
	 * @param endpoint       接口路径，如 /v5/order/create
	 * @param rawRequestBody 原始请求体（JSON 字符串），原样参与签名与发送
	 * @return Bybit 返回的响应体
	 */
	public String post(String credentialName, String endpoint, String rawRequestBody) {
		ApiCredential credential = resolveCredential(credentialName);
		try {
			return postClient.post(
					credential.getApiKey(),
					credential.getApiSecret(),
					endpoint,
					rawRequestBody);
		} catch (Exception e) {
			// 网络或签名异常统一包装，便于上层处理
			throw new RuntimeException("调用 Bybit POST 失败: " + e.getMessage(), e);
		}
	}

	/**
	 * 虚拟盘申请/调整模拟资金（POST /v5/account/demo-apply-money）。
	 * <p>
	 * adjustType 为空时默认 0（增加资金）；请求体按 Bybit 约定构造为 JSON 后走 POST 签名发送。
	 *
	 * @param credentialName 凭证标识（找不到抛 NotFoundException）
	 * @param request        申请明细（adjustType + utaDemoApplyMoney 列表）
	 * @return Bybit 返回的响应体
	 */
	public String applyDemoMoney(String credentialName, DemoApplyMoneyRequest request) {
		// 构造 Bybit 请求体：adjustType 默认 0，明细转为数组
		JSONObject body = new JSONObject();
		body.put("adjustType", request.adjustType() == null ? 0 : request.adjustType());
		JSONArray array = new JSONArray();
		for (var item : request.utaDemoApplyMoney()) {
			array.put(new JSONObject()
					.put("coin", item.coin())
					.put("amountStr", item.amountStr()));
		}
		body.put("utaDemoApplyMoney", array);
		return post(credentialName, DEMO_APPLY_MONEY_ENDPOINT, body.toString());
	}

	/**
	 * 创建委托单（POST /v5/order/create）。
	 * <p>
	 * 请求体由 Jackson3 序列化，DTO 上的 {@code @JsonInclude(NON_NULL)} 会自动省略未设置的字段，
	 * 仅把实际传入的参数发给 Bybit，避免触发因多余字段导致的校验失败。
	 *
	 * @param credentialName 凭证标识（找不到抛 NotFoundException）
	 * @param request        委托单参数（category/symbol/side/orderType/qty 必填）
	 * @return Bybit 返回的响应体（含 orderId / orderLinkId）
	 */
	public String createOrder(String credentialName, CreateOrderRequest request) {
		return post(credentialName, CREATE_ORDER_ENDPOINT, toJson(request));
	}

	// ==================== 通用 GET 透传 ====================

	/**
	 * 通用签名 GET 透传：覆盖持仓/订单/成交等所有需要鉴权的查询接口。
	 * <p>
	 * 调用方传入 Bybit 接口路径与查询参数，服务按凭证签名后调用并原样返回 JSON。
	 * 例：getRaw(name, "/v5/position/list", Map.of("category","linear"))。
	 *
	 * @param credentialName 凭证标识
	 * @param endpoint       Bybit 接口路径
	 * @param params         查询参数（可为 null）
	 */
	public String getRaw(String credentialName, String endpoint, Map<String, String> params) {
		ApiCredential credential = resolveCredential(credentialName);
		try {
			return getClient.get(credential.getApiKey(), credential.getApiSecret(), endpoint, params);
		} catch (Exception e) {
			throw new RuntimeException("调用 Bybit GET 失败: " + e.getMessage(), e);
		}
	}

	/**
	 * 通用公开 GET 透传：覆盖行情类接口（tickers/kline/instruments-info），无需凭证与签名。
	 */
	public String getPublicRaw(String endpoint, Map<String, String> params) {
		try {
			return getClient.getPublic(endpoint, params);
		} catch (Exception e) {
			throw new RuntimeException("调用 Bybit 公开行情失败: " + e.getMessage(), e);
		}
	}

	// ==================== 持仓 / 杠杆 / 止盈止损 ====================

	/** 设置杠杆（POST /v5/position/set-leverage） */
	public String setLeverage(String credentialName, SetLeverageRequest request) {
		return post(credentialName, SET_LEVERAGE_ENDPOINT, toJson(request));
	}

	/** 设置止盈止损（POST /v5/position/trading-stop） */
	public String setTradingStop(String credentialName, TradingStopRequest request) {
		return post(credentialName, TRADING_STOP_ENDPOINT, toJson(request));
	}

	// ==================== 撤单 ====================

	/** 撤销委托单（POST /v5/order/cancel） */
	public String cancelOrder(String credentialName, CancelOrderRequest request) {
		return post(credentialName, CANCEL_ORDER_ENDPOINT, toJson(request));
	}

	/** 撤销所有订单（POST /v5/order/cancel-all） */
	public String cancelAll(String credentialName, CancelAllRequest request) {
		return post(credentialName, CANCEL_ALL_ENDPOINT, toJson(request));
	}

	/**
	 * 按凭证标识解析凭证：优先精确匹配；找不到时回退到第一条凭证（兜底），
	 * 避免"凭证名必须与前端约定一致"的隐性门槛。仍无任何凭证则抛 404。
	 */
	private ApiCredential resolveCredential(String name) {
		return apiCredentialService.findByName(name)
				.or(() -> apiCredentialService.findAll().stream().findFirst()
						.map(fallback -> {
							log.warn("凭证 {} 不存在，回退使用第一条凭证 {}", name, fallback.getName());
							return fallback;
						}))
				.orElseThrow(() -> new NotFoundException("凭证不存在: " + name));
	}

	/** 把 DTO 序列化为 JSON（经 NON_NULL 自动省略空字段） */
	private String toJson(Object request) {
		try {
			return objectMapper.writeValueAsString(request);
		} catch (Exception e) {
			throw new RuntimeException("请求体序列化失败: " + e.getMessage(), e);
		}
	}
}
