package xyz.xingfeng.QuanForge.service;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import xyz.xingfeng.QuanForge.entity.AiConfig;
import xyz.xingfeng.QuanForge.repository.AiConfigRepository;

import java.util.Optional;

/**
 * AI 配置服务：全局单例读写，未配置时提供默认骨架（apiKey 为占位符，调用会失败并提示配置）。
 */
@Service
public class AiConfigService {

	/** 未配置时使用的默认基地址 */
	public static final String DEFAULT_BASE_URL = "https://api.openai.com/v1";

	/** 未配置时使用的默认模型 */
	public static final String DEFAULT_MODEL = "gpt-4o-mini";

	private static final String PLACEHOLDER_KEY = "";

	private final AiConfigRepository repository;

	public AiConfigService(AiConfigRepository repository) {
		this.repository = repository;
	}

	/** 读取配置；不存在时返回内置默认（apiKey 为空串表示未配置） */
	@Transactional
	public AiConfig getConfig() {
		return repository.findById(AiConfig.SINGLETON_ID).orElseGet(() -> {
			AiConfig config = new AiConfig();
			config.setId(AiConfig.SINGLETON_ID);
			config.setBaseUrl(DEFAULT_BASE_URL);
			config.setApiKey(PLACEHOLDER_KEY);
			config.setModel(DEFAULT_MODEL);
			config.setEnabled(Boolean.FALSE);
			return repository.save(config);
		});
	}

	/** 是否已配置可用的 API Key */
	@Transactional(readOnly = true)
	public boolean isConfigured() {
		return repository.findById(AiConfig.SINGLETON_ID)
				.map(c -> c.getApiKey() != null && !c.getApiKey().isBlank())
				.orElse(false);
	}

	/** 保存配置（apiKey 为 null/空白时保留旧值，便于只改其他项） */
	@Transactional
	public AiConfig save(String baseUrl, String apiKey, String model, Boolean enabled,
			String watchSymbols, Integer scanIntervalMinutes, Double changeThresholdPct,
			Boolean newsKeywordOn, Integer leverage, Double minMovePct, String strategyNote) {
		AiConfig config = getConfig();
		if (baseUrl != null && !baseUrl.isBlank()) {
			config.setBaseUrl(stripTrailingSlash(baseUrl.trim()));
		}
		if (apiKey != null && !apiKey.isBlank()) {
			config.setApiKey(apiKey.trim());
		}
		if (model != null && !model.isBlank()) {
			config.setModel(model.trim());
		}
		if (enabled != null) {
			config.setEnabled(enabled);
		}
		if (watchSymbols != null && !watchSymbols.isBlank()) {
			config.setWatchSymbols(normalizeSymbols(watchSymbols));
		}
		if (scanIntervalMinutes != null && scanIntervalMinutes >= 1 && scanIntervalMinutes <= 1440) {
			config.setScanIntervalMinutes(scanIntervalMinutes);
		}
		if (changeThresholdPct != null && changeThresholdPct > 0 && changeThresholdPct <= 50) {
			config.setChangeThresholdPct(changeThresholdPct);
		}
		if (newsKeywordOn != null) {
			config.setNewsKeywordOn(newsKeywordOn);
		}
		if (leverage != null && leverage >= 1 && leverage <= 200) {
			config.setLeverage(leverage);
		}
		if (minMovePct != null && minMovePct > 0 && minMovePct <= 10) {
			config.setMinMovePct(minMovePct);
		}
		if (strategyNote != null) {
			config.setStrategyNote(strategyNote.trim().length() > 1000
					? strategyNote.trim().substring(0, 1000) : strategyNote.trim());
		}
		return repository.save(config);
	}

	/** 去掉 baseUrl 结尾的 /（拼 chat/completions 时统一处理） */
	private String stripTrailingSlash(String url) {
		return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
	}

	/** 品种列表标准化：逗号分隔、去空格、去重、转大写 */
	private String normalizeSymbols(String raw) {
		java.util.LinkedHashSet<String> set = new java.util.LinkedHashSet<>();
		for (String part : raw.split("[,，\\s]+")) {
			if (!part.isBlank()) {
				set.add(part.trim().toUpperCase());
			}
		}
		return String.join(",", set);
	}

	/** API Key 打码（前端展示用） */
	public String maskKey(AiConfig config) {
		String key = config.getApiKey();
		if (key == null || key.isEmpty()) {
			return "";
		}
		if (key.length() <= 8) {
			return "****";
		}
		return key.substring(0, 4) + "****" + key.substring(key.length() - 4);
	}

	/** 盯盘品种列表 */
	public java.util.List<String> watchList(AiConfig config) {
		return Optional.ofNullable(config.getWatchSymbols())
				.filter(s -> !s.isBlank())
				.map(s -> java.util.Arrays.asList(s.split(",")))
				.orElseGet(java.util.List::of);
	}
}
