package xyz.xingfeng.QuanForge.controller;

import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import xyz.xingfeng.QuanForge.dto.AiConfigRequest;
import xyz.xingfeng.QuanForge.dto.AiConfigResponse;
import xyz.xingfeng.QuanForge.entity.AiAdviceTrack;
import xyz.xingfeng.QuanForge.entity.AiAlert;
import xyz.xingfeng.QuanForge.entity.AiConfig;
import xyz.xingfeng.QuanForge.repository.AiAlertRepository;
import xyz.xingfeng.QuanForge.service.AiAdviceTracker;
import xyz.xingfeng.QuanForge.service.AiAnalysisService;
import xyz.xingfeng.QuanForge.service.AiConfigService;

import java.util.List;
import java.util.Map;

/**
 * AI 盯盘接口：配置读写、告警查询、手动分析、建议纸面跟踪。
 */
@RestController
@RequestMapping("/api/ai")
public class AiController {

	private final AiConfigService configService;
	private final AiAnalysisService analysisService;
	private final AiAlertRepository alertRepository;
	private final AiAdviceTracker adviceTracker;

	public AiController(AiConfigService configService, AiAnalysisService analysisService,
			AiAlertRepository alertRepository, AiAdviceTracker adviceTracker) {
		this.configService = configService;
		this.analysisService = analysisService;
		this.alertRepository = alertRepository;
		this.adviceTracker = adviceTracker;
	}

	/** 当前 AI 配置（Key 打码） */
	@GetMapping("/config")
	public AiConfigResponse getConfig() {
		AiConfig config = configService.getConfig();
		return toResponse(config);
	}

	/** 保存配置（apiKey 为空表示保留旧值） */
	@PutMapping("/config")
	public AiConfigResponse saveConfig(@Valid @RequestBody AiConfigRequest req) {
		AiConfig saved = configService.save(req.baseUrl(), req.apiKey(), req.model(),
				req.enabled(), req.watchSymbols(), req.scanIntervalMinutes(),
				req.changeThresholdPct(), req.newsKeywordOn(),
				req.leverage(), req.minMovePct(), req.strategyNote());
		return toResponse(saved);
	}

	/** 最近告警（时间倒序） */
	@GetMapping("/alerts")
	public List<AiAlert> alerts(@RequestParam(defaultValue = "20") int limit) {
		List<AiAlert> all = alertRepository.findTop50ByOrderByCreatedAtDesc();
		int n = Math.min(Math.max(limit, 1), all.size());
		return all.subList(0, n);
	}

	/** 最近纸面跟踪记录（时间倒序） */
	@GetMapping("/tracks")
	public List<AiAdviceTrack> tracks(@RequestParam(defaultValue = "20") int limit) {
		return adviceTracker.recent(limit);
	}

	/** 纸面跟踪胜率统计 */
	@GetMapping("/tracks/stats")
	public Map<String, Object> trackStats() {
		return adviceTracker.stats();
	}

	/** 手动对指定品种做一次 AI 分析 */
	@PostMapping("/analyze")
	public ResponseEntity<?> analyze(@RequestParam String symbol) {
		try {
			AiAlert alert = analysisService.analyzeNow(symbol);
			if (alert == null) {
				return ResponseEntity.ok(Map.of("ok", false, "message", "K 线数据不足，无法分析"));
			}
			return ResponseEntity.ok(alert);
		} catch (IllegalStateException e) {
			return ResponseEntity.badRequest().body(Map.of("ok", false, "message", e.getMessage()));
		} catch (Exception e) {
			return ResponseEntity.status(502).body(Map.of(
					"ok", false,
					"message", "AI 调用失败: " + e.getMessage()));
		}
	}

	private AiConfigResponse toResponse(AiConfig config) {
		boolean keySet = config.getApiKey() != null && !config.getApiKey().isBlank();
		return new AiConfigResponse(
				config.getBaseUrl(),
				keySet ? configService.maskKey(config) : "",
				keySet,
				config.getModel(),
				Boolean.TRUE.equals(config.getEnabled()),
				config.getWatchSymbols(),
				config.getScanIntervalMinutes(),
				config.getChangeThresholdPct(),
				Boolean.TRUE.equals(config.getNewsKeywordOn()),
				config.getLeverage() == null ? 100 : config.getLeverage(),
				config.getMinMovePct() == null ? 0.1 : config.getMinMovePct(),
				config.getStrategyNote() == null ? "" : config.getStrategyNote());
	}
}
