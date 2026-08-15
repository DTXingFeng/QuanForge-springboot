package xyz.xingfeng.QuanForge.dto;

import xyz.xingfeng.QuanForge.entity.ApiCredential;

import java.time.LocalDateTime;

/**
 * 凭证列表响应（脱敏）：不暴露完整密钥与 secret。
 */
public record ApiCredentialResponse(
		Long id,
		String name,
		String maskedApiKey,
		LocalDateTime createdAt,
		LocalDateTime updatedAt) {

	public static ApiCredentialResponse from(ApiCredential c) {
		return new ApiCredentialResponse(c.getId(), c.getName(), mask(c.getApiKey()), c.getCreatedAt(), c.getUpdatedAt());
	}

	/** 脱敏：长度大于 8 时保留首尾各 4 位，中间以星号替代；过短则全部星号 */
	private static String mask(String value) {
		if (value == null) {
			return null;
		}
		if (value.length() <= 8) {
			return "********";
		}
		return value.substring(0, 4) + "********" + value.substring(value.length() - 4);
	}
}
