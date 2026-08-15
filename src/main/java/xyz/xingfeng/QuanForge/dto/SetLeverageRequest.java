package xyz.xingfeng.QuanForge.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import jakarta.validation.constraints.NotBlank;

/**
 * 设置杠杆请求体（POST /v5/position/set-leverage）。
 * <p>
 * 仅 linear / inverse 有效；buyLeverage / sellLeverage 为字符串形式（如 "100"）。
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record SetLeverageRequest(
		@NotBlank(message = "category 不能为空") String category,
		@NotBlank(message = "symbol 不能为空") String symbol,
		@NotBlank(message = "buyLeverage 不能为空") String buyLeverage,
		@NotBlank(message = "sellLeverage 不能为空") String sellLeverage) {
}
