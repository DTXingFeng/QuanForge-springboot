package xyz.xingfeng.QuanForge.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import jakarta.validation.constraints.NotBlank;

/**
 * 创建委托单请求体（POST /v5/order/create）。
 * <p>
 * 覆盖 Bybit 全部参数；仅 5 个必填字段做非空校验，其余为空时通过
 * {@link JsonInclude.Include#NON_NULL} 自动省略，避免向 Bybit 传送多余字段。
 * <p>
 * 必填：category / symbol / side / orderType / qty。
 * 枚举值（Bybit 会再次校验）：
 * <ul>
 *   <li>category: spot / linear / inverse / option</li>
 *   <li>side: Buy / Sell</li>
 *   <li>orderType: Market / Limit</li>
 *   <li>timeInForce: GTC / IOC / FOK / PostOnly</li>
 * </ul>
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record CreateOrderRequest(
		// ===== 必填 =====
		@NotBlank(message = "category 不能为空") String category,
		@NotBlank(message = "symbol 不能为空") String symbol,
		@NotBlank(message = "side 不能为空") String side,
		@NotBlank(message = "orderType 不能为空") String orderType,
		@NotBlank(message = "qty 不能为空") String qty,

		// ===== 价格 / 数量 / 策略 =====
		String price,
		String timeInForce,
		String marketUnit,
		Integer isLeverage,
		String orderFilter,

		// ===== 条件单 =====
		String triggerPrice,
		String triggerBy,
		Integer triggerDirection,

		// ===== 期权 =====
		String orderIv,

		// ===== 持仓 / 自定义 =====
		Integer positionIdx,
		String orderLinkId,

		// ===== 止盈止损 =====
		String takeProfit,
		String stopLoss,
		String tpTriggerBy,
		String slTriggerBy,
		String tpslMode,
		String tpOrderType,
		String slOrderType,
		String tpLimitPrice,
		String slLimitPrice,

		// ===== 风控 / 标识 =====
		Boolean reduceOnly,
		Boolean closeOnTrigger,
		Boolean mmp,
		String smpType,

		// ===== 市价滑点 =====
		String slippageToleranceType,
		String slippageTolerance,

		// ===== RPI / BBO =====
		Boolean rpiTakerAccess,
		String bboSideType,
		String bboLevel) {
}
