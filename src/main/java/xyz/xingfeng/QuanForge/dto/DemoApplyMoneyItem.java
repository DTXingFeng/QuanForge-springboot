package xyz.xingfeng.QuanForge.dto;

import jakarta.validation.constraints.NotBlank;

/**
 * demo-apply-money 单项：申请的币种与金额。
 */
public record DemoApplyMoneyItem(
		@NotBlank(message = "coin 不能为空") String coin,
		@NotBlank(message = "amountStr 不能为空") String amountStr) {
}
