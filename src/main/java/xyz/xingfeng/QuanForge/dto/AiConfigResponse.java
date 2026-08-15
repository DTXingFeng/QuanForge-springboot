package xyz.xingfeng.QuanForge.dto;

/**
 * AI 配置响应（API Key 打码）。
 */
public record AiConfigResponse(
		String baseUrl,
		String maskedApiKey,
		boolean apiKeySet,
		String model,
		boolean enabled,
		String watchSymbols,
		int scanIntervalMinutes,
		double changeThresholdPct,
		boolean newsKeywordOn,
		int leverage,
		double minMovePct,
		String strategyNote) {
}
