package xyz.xingfeng.QuanForge.dto;

import jakarta.validation.constraints.NotBlank;

/**
 * 创建/更新凭证的请求体。
 */
public record ApiCredentialRequest(
		@NotBlank(message = "name 不能为空") String name,
		@NotBlank(message = "apiKey 不能为空") String apiKey,
		@NotBlank(message = "apiSecret 不能为空") String apiSecret) {
}
