package xyz.xingfeng.QuanForge.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import jakarta.validation.constraints.NotBlank;

/**
 * 撤销所有订单请求体（POST /v5/order/cancel-all）。
 * <p>
 * category 必填；其余为筛选条件，linear/inverse 不传 baseCoin/settleCoin 时 symbol 必传。
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record CancelAllRequest(
		@NotBlank(message = "category 不能为空") String category,
		String symbol,
		String baseCoin,
		String settleCoin,
		String orderFilter,
		String stopOrderType) {
}
