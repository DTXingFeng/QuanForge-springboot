package xyz.xingfeng.QuanForge.service;

import org.json.JSONArray;
import org.json.JSONObject;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import xyz.xingfeng.QuanForge.entity.Kline1m;
import xyz.xingfeng.QuanForge.repository.Kline1mRepository;

import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * 1m K 线历史下载器：模型训练数据管道。
 * Bybit /v5/market/kline 单次上限 1000 根，按时间窗翻页拉取入库（去重靠主键 upsert-ignore）。
 * 下载为 @Async 后台任务，进度可通过 count 接口观察。
 */
@Service
public class KlineHistoryService {

	private static final Logger log = LoggerFactory.getLogger(KlineHistoryService.class);

	private static final long MINUTE_MS = 60_000L;

	private final Kline1mRepository repository;
	private final BybitService bybitService;

	/** 下载进度标记（symbol -> 是否在跑） */
	private final Map<String, Boolean> running = new java.util.concurrent.ConcurrentHashMap<>();

	public KlineHistoryService(Kline1mRepository repository, BybitService bybitService) {
		this.repository = repository;
		this.bybitService = bybitService;
	}

	/** 后台批量下载：从 earliest 往前补到 now（幂等，可重复执行只补增量） */
	@Async
	@Transactional(propagation = Propagation.NOT_SUPPORTED)
	public CompletableFuture<String> download(String symbol, LocalDateTime earliest) {
		symbol = symbol.toUpperCase();
		if ("true".equals(String.valueOf(running.put(symbol, true)))) {
			return CompletableFuture.completedFuture(symbol + " 已有下载任务在跑");
		}
		try {
			LocalDateTime from = earliest;
			LocalDateTime latest = repository.latestOpenTime(symbol);
			if (latest != null && latest.isAfter(from)) {
				from = latest; // 增量：从库里最后一根继续
			}
			long total = 0;
			LocalDateTime cursor = from;
			LocalDateTime now = LocalDateTime.now();
			while (cursor.isBefore(now)) {
				// Bybit: start/end 为毫秒时间戳，窗口 [start, end]，倒序返回
				long startMs = cursor.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli();
				long endMs = startMs + 1000 * MINUTE_MS - 1;
				int inserted = fetchAndSave(symbol, startMs, endMs);
				total += inserted;
				cursor = cursor.plusMinutes(1000);
				if (inserted == 0 && cursor.isBefore(now.plusHours(1))) {
					// 连续空窗（新上市币）跳过时间但继续
					log.debug("{} 在 {} 后无数据", symbol, cursor);
				}
			}
			String msg = String.format("%s 下载完成：新增 %d 根，库内共 %d 根",
					symbol, total, repository.countBySymbol(symbol));
			log.info("[KlineDL] {}", msg);
			return CompletableFuture.completedFuture(msg);
		} catch (Exception e) {
			log.warn("[KlineDL] {} 下载失败: {}", symbol, e.getMessage());
			return CompletableFuture.completedFuture(symbol + " 下载失败: " + e.getMessage());
		} finally {
			running.remove(symbol);
		}
	}

	/** 拉一窗并入库；已存在的主键冲突行忽略 */
	@Transactional
	int fetchAndSave(String symbol, long startMs, long endMs) throws Exception {
		String json = bybitService.getPublicRaw("/v5/market/kline", Map.of(
				"category", "linear", "symbol", symbol, "interval", "1",
				"start", String.valueOf(startMs), "end", String.valueOf(endMs), "limit", "1000"));
		JSONObject resp = new JSONObject(json);
		if (resp.getInt("retCode") != 0) {
			throw new IllegalStateException("Bybit kline: " + resp.getString("retMsg"));
		}
		JSONArray list = resp.getJSONObject("result").getJSONArray("list");
		List<Kline1m> rows = new ArrayList<>();
		ZoneId zone = ZoneId.systemDefault();
		for (int i = 0; i < list.length(); i++) {
			JSONArray k = list.getJSONArray(i);
			// Bybit 元素 [start, open, high, low, close, volume, turnover]
			LocalDateTime openTime = LocalDateTime.ofInstant(
					Instant.ofEpochMilli(k.getLong(0)), zone);
			rows.add(new Kline1m(symbol, openTime,
					k.getDouble(1), k.getDouble(2), k.getDouble(3), k.getDouble(4),
					k.getDouble(5), k.getDouble(6)));
		}
		if (rows.isEmpty()) {
			return 0;
		}
		// 主键已存在的行 save 会 merge 覆盖——历史 K 线值相同，无害；冲突行极少
		repository.saveAll(rows);
		return rows.size();
	}

	public boolean isRunning(String symbol) {
		return Boolean.TRUE.equals(running.get(symbol.toUpperCase()));
	}
}
