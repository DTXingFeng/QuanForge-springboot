package xyz.xingfeng.QuanForge.dto;

import xyz.xingfeng.QuanForge.entity.ApiCredential;

import java.time.LocalDateTime;

/**
 * 凭证详情响应（明文）：管理用途，返回完整 apiKey 与 apiSecret。
 */
public record ApiCredentialDetailResponse(
		Long id,
		String name,
		String apiKey,
		String apiSecret,
		LocalDateTime createdAt,
		LocalDateTime updatedAt) {

	public static ApiCredentialDetailResponse from(ApiCredential c) {
		return new ApiCredentialDetailResponse(
				c.getId(), c.getName(), c.getApiKey(), c.getApiSecret(), c.getCreatedAt(), c.getUpdatedAt());
	}
}
