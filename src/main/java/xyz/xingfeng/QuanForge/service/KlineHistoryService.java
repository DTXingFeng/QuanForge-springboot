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

	/** 下载队列：SQLite 池只有 1 连接，多任务并发会互相饿死（含盯盘调度），必须全局串行 */
	private final java.util.concurrent.locks.ReentrantLock downloadLock =
			new java.util.concurrent.locks.ReentrantLock(true);

	/** 后台批量下载：从 earliest 往前补到 now（幂等，可重复执行只补增量）。全局排队执行。 */
	@Async
	@Transactional(propagation = Propagation.NOT_SUPPORTED)
	public CompletableFuture<String> download(String symbol, LocalDateTime earliest) {
		symbol = symbol.toUpperCase();
		if ("true".equals(String.valueOf(running.put(symbol, true)))) {
			return CompletableFuture.completedFuture(symbol + " 已有下载任务在跑");
		}
		try {
			downloadLock.lock();
			try {
				return CompletableFuture.completedFuture(doDownload(symbol, earliest));
			} finally {
				downloadLock.unlock();
			}
		} finally {
			running.remove(symbol);
		}
	}

	private String doDownload(String symbol, LocalDateTime earliest) {
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
				// HTTP 在无事务上下文执行（不占连接）；仅 saveAll 开短事务
				List<Kline1m> rows = fetch(symbol, startMs, endMs);
				if (!rows.isEmpty()) {
					saveBatch(rows);
				}
				total += rows.size();
				cursor = cursor.plusMinutes(1000);
				Thread.sleep(150); // 对 Bybit 限速礼貌：每窗之间歇一下
			}
			String msg = String.format("%s 下载完成：新增 %d 根，库内共 %d 根",
					symbol, total, repository.countBySymbol(symbol));
			log.info("[KlineDL] {}", msg);
			return msg;
		} catch (Exception e) {
			log.warn("[KlineDL] {} 下载失败: {}", symbol, e.getMessage());
			return symbol + " 下载失败: " + e.getMessage();
		}
	}

	/** 拉一窗 K 线（无事务上下文，不占数据库连接） */
	private List<Kline1m> fetch(String symbol, long startMs, long endMs) throws Exception {
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
		return rows;
	}

	/** 批量入库（短事务：批量提交，减少连接占用时间） */
	@Transactional
	void saveBatch(List<Kline1m> rows) {
		repository.saveAll(rows);
	}

	public boolean isRunning(String symbol) {
		return Boolean.TRUE.equals(running.get(symbol.toUpperCase()));
	}
}
