package xyz.xingfeng.QuanForge.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotEmpty;

import java.util.List;

/**
 * 虚拟盘申请/调整模拟资金请求体。
 *
 * @param adjustType       0(默认):增加模拟资金; 1:减少模拟资金；为空时按 0 处理
 * @param utaDemoApplyMoney 申请的资金明细列表（币种 + 金额）
 */
public record DemoApplyMoneyRequest(
		@Min(value = 0, message = "adjustType 只能为 0 或 1")
		@Max(value = 1, message = "adjustType 只能为 0 或 1")
		Integer adjustType,
		@NotEmpty(message = "utaDemoApplyMoney 不能为空")
		List<DemoApplyMoneyItem> utaDemoApplyMoney) {
}
