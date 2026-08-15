package xyz.xingfeng.QuanForge.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import xyz.xingfeng.QuanForge.entity.ProxyType;

/**
 * 保存代理配置的请求体。username/password 可选（无认证代理留空）。
 */
public record ProxyConfigRequest(
		@NotNull(message = "type 不能为空") ProxyType type,
		@NotBlank(message = "host 不能为空") String host,
		@NotNull(message = "port 不能为空") @Min(value = 1, message = "port 非法") @Max(value = 65535, message = "port 非法") Integer port,
		String username,
		String password,
		Boolean enabled,
		Boolean useForAi) {
}
