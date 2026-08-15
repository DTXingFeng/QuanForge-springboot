package xyz.xingfeng.QuanForge.controller;

import jakarta.validation.Valid;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import xyz.xingfeng.QuanForge.dto.CancelAllRequest;
import xyz.xingfeng.QuanForge.dto.CancelOrderRequest;
import xyz.xingfeng.QuanForge.client.BybitMode;
import xyz.xingfeng.QuanForge.client.BybitModeHolder;
import xyz.xingfeng.QuanForge.dto.CreateOrderRequest;
import xyz.xingfeng.QuanForge.dto.DemoApplyMoneyRequest;
import xyz.xingfeng.QuanForge.dto.ModeRequest;
import xyz.xingfeng.QuanForge.dto.SetLeverageRequest;
import xyz.xingfeng.QuanForge.dto.TradingStopRequest;
import xyz.xingfeng.QuanForge.service.BybitService;

import java.util.Map;

/**
 * Bybit 接口入口：对外暴露 Bybit V5 调用。
 */
@RestController
@RequestMapping("/api/bybit")
public class BybitController {

	private final BybitService bybitService;
	private final BybitModeHolder modeHolder;

	public BybitController(BybitService bybitService, BybitModeHolder modeHolder) {
		this.bybitService = bybitService;
		this.modeHolder = modeHolder;
	}

	/** 查询当前运行模式（REAL 实盘 / DEMO 虚拟盘） */
	@GetMapping("/mode")
	public Map<String, String> mode() {
		return Map.of("mode", modeHolder.getMode().name());
	}

	/** 切换运行模式（REAL 实盘 / DEMO 虚拟盘），body: {"mode":"DEMO"} */
	@PutMapping("/mode")
	public Map<String, String> setMode(@Valid @RequestBody ModeRequest request) {
		BybitMode mode = BybitMode.valueOf(request.mode().trim().toUpperCase());
		modeHolder.setMode(mode);
		return Map.of("mode", mode.name());
	}

	/** 查询统一账户钱包余额；name 指定凭证标识，默认 bybit，使用当前运行模式地址 */
	@GetMapping("/wallet-balance")
	public ResponseEntity<String> walletBalance(
			@RequestParam(defaultValue = BybitService.DEFAULT_CREDENTIAL_NAME) String name) {
		String json = bybitService.getUnifiedWalletBalance(name);
		// 原样透传 Bybit 返回的 JSON
		return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(json);
	}

	/**
	 * 发起 Bybit V5 POST 请求（签名串使用请求体原文）。
	 * <p>
	 * 请求体以 application/json 原样透传给 Bybit；name 指定凭证标识，endpoint 指定接口路径。
	 *
	 * @param name     凭证标识，默认 bybit
	 * @param endpoint 接口路径，如 /v5/order/create
	 * @param body     原始请求体（JSON 字符串）
	 */
	@PostMapping("/post")
	public ResponseEntity<String> post(
			@RequestParam(defaultValue = BybitService.DEFAULT_CREDENTIAL_NAME) String name,
			@RequestParam String endpoint,
			@RequestBody(required = false) String body) {
		String json = bybitService.post(name, endpoint, body == null ? "" : body);
		// 原样透传 Bybit 返回的 JSON
		return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(json);
	}

	/**
	 * 虚拟盘申请/调整模拟资金（POST /v5/account/demo-apply-money）。
	 * <p>
	 * adjustType 为空时默认 0（增加资金）。请求体经校验后转发给 Bybit。
	 *
	 * @param name    凭证标识，默认 bybit
	 * @param request adjustType + utaDemoApplyMoney 明细
	 */
	@PostMapping("/demo-apply-money")
	public ResponseEntity<String> demoApplyMoney(
			@RequestParam(defaultValue = BybitService.DEFAULT_CREDENTIAL_NAME) String name,
			@Valid @RequestBody DemoApplyMoneyRequest request) {
		String json = bybitService.applyDemoMoney(name, request);
		// 原样透传 Bybit 返回的 JSON
		return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(json);
	}

	/**
	 * 创建委托单（POST /v5/order/create）。
	 * <p>
	 * 必填：category / symbol / side / orderType / qty；其余字段为空时自动省略。
	 *
	 * @param name    凭证标识，默认 bybit
	 * @param request 委托单参数
	 */
	@PostMapping("/create-order")
	public ResponseEntity<String> createOrder(
			@RequestParam(defaultValue = BybitService.DEFAULT_CREDENTIAL_NAME) String name,
			@Valid @RequestBody CreateOrderRequest request) {
		String json = bybitService.createOrder(name, request);
		// 原样透传 Bybit 返回的 JSON（含 orderId / orderLinkId）
		return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(json);
	}

	// ==================== 通用 GET 透传（覆盖所有查询接口） ====================

	/**
	 * 通用签名 GET 透传：覆盖持仓/订单/成交/平仓盈亏等所有需鉴权的查询接口。
	 * <p>
	 * 除 name、endpoint 外，其余 query 参数原样转发给 Bybit。
	 * 例：GET /api/bybit/get?name=x&amp;endpoint=/v5/position/list&amp;category=linear
	 */
	@GetMapping("/get")
	public ResponseEntity<String> getBybit(
			@RequestParam(defaultValue = BybitService.DEFAULT_CREDENTIAL_NAME) String name,
			@RequestParam String endpoint,
			@RequestParam Map<String, String> params) {
		// 剔除路由自身使用的参数，剩余全部作为 Bybit 查询参数
		params.remove("name");
		params.remove("endpoint");
		String json = bybitService.getRaw(name, endpoint, params);
		return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(json);
	}

	/**
	 * 通用公开 GET 透传：覆盖行情类接口（tickers/kline/instruments-info），无需凭证。
	 * <p>
	 * 除 endpoint 外，其余 query 参数原样转发。例：GET /api/bybit/market?endpoint=/v5/market/kline&amp;symbol=BTCUSDT&amp;interval=60
	 */
	@GetMapping("/market")
	public ResponseEntity<String> market(
			@RequestParam String endpoint,
			@RequestParam Map<String, String> params) {
		params.remove("endpoint");
		String json = bybitService.getPublicRaw(endpoint, params);
		return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(json);
	}

	// ==================== 持仓 / 杠杆 / 止盈止损 ====================

	/** 设置杠杆（POST /v5/position/set-leverage） */
	@PostMapping("/set-leverage")
	public ResponseEntity<String> setLeverage(
			@RequestParam(defaultValue = BybitService.DEFAULT_CREDENTIAL_NAME) String name,
			@Valid @RequestBody SetLeverageRequest request) {
		String json = bybitService.setLeverage(name, request);
		return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(json);
	}

	/** 设置止盈止损（POST /v5/position/trading-stop） */
	@PostMapping("/trading-stop")
	public ResponseEntity<String> tradingStop(
			@RequestParam(defaultValue = BybitService.DEFAULT_CREDENTIAL_NAME) String name,
			@Valid @RequestBody TradingStopRequest request) {
		String json = bybitService.setTradingStop(name, request);
		return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(json);
	}

	// ==================== 撤单 ====================

	/** 撤销委托单（POST /v5/order/cancel） */
	@PostMapping("/cancel-order")
	public ResponseEntity<String> cancelOrder(
			@RequestParam(defaultValue = BybitService.DEFAULT_CREDENTIAL_NAME) String name,
			@Valid @RequestBody CancelOrderRequest request) {
		String json = bybitService.cancelOrder(name, request);
		return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(json);
	}

	/** 撤销所有订单（POST /v5/order/cancel-all） */
	@PostMapping("/cancel-all")
	public ResponseEntity<String> cancelAll(
			@RequestParam(defaultValue = BybitService.DEFAULT_CREDENTIAL_NAME) String name,
			@Valid @RequestBody CancelAllRequest request) {
		String json = bybitService.cancelAll(name, request);
		return ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(json);
	}
}
