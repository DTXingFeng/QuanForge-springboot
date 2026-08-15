package xyz.xingfeng.QuanForge.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

/**
 * 设置止盈止损请求体（POST /v5/position/trading-stop）。
 * <p>
 * 必填：category / symbol / tpslMode / positionIdx。其余可选字段为空时自动省略；
 * takeProfit/stopLoss/trailingStop 传 "0" 表示取消，不修改则不要传。
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record TradingStopRequest(
		@NotBlank(message = "category 不能为空") String category,
		@NotBlank(message = "symbol 不能为空") String symbol,
		@NotBlank(message = "tpslMode 不能为空") String tpslMode,
		@NotNull(message = "positionIdx 不能为空") Integer positionIdx,
		String takeProfit,
		String stopLoss,
		String trailingStop,
		String tpTriggerBy,
		String slTriggerBy,
		String activePrice,
		String tpSize,
		String slSize,
		String tpLimitPrice,
		String slLimitPrice,
		String tpOrderType,
		String slOrderType) {
}
