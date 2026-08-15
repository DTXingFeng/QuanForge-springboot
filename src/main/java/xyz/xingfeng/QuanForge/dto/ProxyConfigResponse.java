package xyz.xingfeng.QuanForge.dto;

import xyz.xingfeng.QuanForge.entity.ProxyConfig;
import xyz.xingfeng.QuanForge.entity.ProxyType;

import java.time.LocalDateTime;

/**
 * 代理配置响应。
 */
public record ProxyConfigResponse(
		Long id,
		ProxyType type,
		String host,
		Integer port,
		String username,
		String password,
		Boolean enabled,
		Boolean useForAi,
		LocalDateTime createdAt,
		LocalDateTime updatedAt) {

	public static ProxyConfigResponse from(ProxyConfig c) {
		return new ProxyConfigResponse(
				c.getId(), c.getType(), c.getHost(), c.getPort(),
				c.getUsername(), c.getPassword(), c.getEnabled(),
				c.getUseForAi() == null ? Boolean.TRUE : c.getUseForAi(),
				c.getCreatedAt(), c.getUpdatedAt());
	}
}
