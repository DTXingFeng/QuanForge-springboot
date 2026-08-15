package xyz.xingfeng.QuanForge.dto;

/**
 * 保存 AI 配置的请求体。apiKey 留空表示不修改（便于只改盯盘参数）。
 */
public record AiConfigRequest(
		String baseUrl,
		String apiKey,
		String model,
		Boolean enabled,
		String watchSymbols,
		Integer scanIntervalMinutes,
		Double changeThresholdPct,
		Boolean newsKeywordOn,
		Integer leverage,
		Double minMovePct,
		String strategyNote) {
}
