package xyz.xingfeng.QuanForge.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import jakarta.validation.constraints.NotBlank;

/**
 * 撤销委托单请求体（POST /v5/order/cancel）。
 * <p>
 * orderId 与 orderLinkId 二选一必传；orderFilter 仅现货有效。
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record CancelOrderRequest(
		@NotBlank(message = "category 不能为空") String category,
		@NotBlank(message = "symbol 不能为空") String symbol,
		String orderId,
		String orderLinkId,
		String orderFilter) {
}
