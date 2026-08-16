package xyz.xingfeng.QuanForge.controller;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import xyz.xingfeng.QuanForge.repository.Kline1mRepository;
import xyz.xingfeng.QuanForge.service.KlineHistoryService;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * K 线历史数据管道接口：下载触发 + 进度查询。
 * 训练数据准备用，非前端常规路径。
 */
@RestController
@RequestMapping("/api/kline")
public class KlineHistoryController {

	private final KlineHistoryService service;
	private final Kline1mRepository repository;

	public KlineHistoryController(KlineHistoryService service, Kline1mRepository repository) {
		this.service = service;
		this.repository = repository;
	}

	/** 触发后台下载（days = 往回补的天数；幂等增量） */
	@PostMapping("/download")
	public ResponseEntity<?> download(@RequestParam String symbol, @RequestParam int days) {
		if (days < 1 || days > 365) {
			return ResponseEntity.badRequest().body(Map.of("ok", false, "message", "days 1~365"));
		}
		LocalDateTime earliest = LocalDateTime.now().minusDays(days);
		service.download(symbol, earliest);
		return ResponseEntity.accepted().body(Map.of("ok", true, "message",
				symbol + " 后台下载已启动（" + days + " 天），稍后用 /api/kline/count 查进度"));
	}

	/** 各品种入库根数 */
	@GetMapping("/count")
	public Map<String, Object> count() {
		Map<String, Object> m = new LinkedHashMap<>();
		for (String s : new String[] { "BTCUSDT", "ETHUSDT", "SOLUSDT", "HEMIUSDT", "HYPEUSDT",
				"CYSUSDT", "BEATUSDT", "ACEUSDT" }) {
			m.put(s, Map.of("count", repository.countBySymbol(s),
					"running", service.isRunning(s)));
		}
		return m;
	}
}
