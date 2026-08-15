package xyz.xingfeng.QuanForge.controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import xyz.xingfeng.QuanForge.service.NewsService;

import java.util.List;
import java.util.Map;

/**
 * 快讯接口：HTX 式快讯流数据源。
 */
@RestController
public class NewsController {

	private final NewsService newsService;

	public NewsController(NewsService newsService) {
		this.newsService = newsService;
	}

	/**
	 * 最新快讯（时间倒序）。
	 * 例：GET /api/news?limit=50&source=华尔街见闻
	 */
	@GetMapping("/api/news")
	public Map<String, Object> news(
			@RequestParam(defaultValue = "50") int limit,
			@RequestParam(defaultValue = "all") String source) {
		List<NewsService.NewsItem> items = newsService.latest(Math.min(Math.max(limit, 1), 200), source);
		return Map.of(
				"items", items,
				"lastRefreshAt", newsService.getLastRefreshAt());
	}
}
