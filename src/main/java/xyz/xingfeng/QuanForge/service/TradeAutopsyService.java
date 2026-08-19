package xyz.xingfeng.QuanForge.service;

import org.json.JSONArray;
import org.json.JSONObject;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import xyz.xingfeng.QuanForge.entity.AiAdviceTrack;
import xyz.xingfeng.QuanForge.repository.AiAdviceTrackRepository;

import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * 交易验尸统计：把已结算单按死因分类（K 线重放），输出供 LLM 解读的结构化摘要。
 * <p>
 * 分类学（与 tools/trade_autopsy.py 同口径）：
 * <ul>
 *   <li>LOSS-chop-stop：止损打掉后 4h 内价格到达止盈位——方向对，止损位错（REBASE 靶子）</li>
 *   <li>LOSS-right-side-trend：打掉后继续逆行 >1.5×止损距——方向本身就错（研判问题）</li>
 *   <li>LOSS-drift-flat：既不恢复也不崩——无边界震荡磨损（出手时机问题）</li>
 *   <li>WIN-capped-early：止盈后趋势延续 >50% 止盈距——利润截断（持盈问题）</li>
 *   <li>WIN-clean：止盈即衰竭——干净赢</li>
 * </ul>
 * K 线重放开销大（每单 ~200 根 1m），验尸按需触发（/autopsy 命令/周报），不进定时任务。
 */
@Service
public class TradeAutopsyService {

	private static final Logger log = LoggerFactory.getLogger(TradeAutopsyService.class);

	private final AiAdviceTrackRepository repository;
	private final BybitService bybitService;
	private final AiConfigService configService;
	private final xyz.xingfeng.QuanForge.client.ProxiedHttpClients clients;

	public TradeAutopsyService(AiAdviceTrackRepository repository, BybitService bybitService,
			AiConfigService configService, xyz.xingfeng.QuanForge.client.ProxiedHttpClients clients) {
		this.repository = repository;
		this.bybitService = bybitService;
		this.configService = configService;
		this.clients = clients;
	}

	/** 死因分类结果：类别 → [数量, 代表案例文本] */
	public record Autopsy(int wins, int losses, Map<String, Integer> taxonomy,
			Map<String, String> examples) {
	}

	/**
	 * LLM 解读：把死因分布翻译成交易员语言——最大的钱漏在哪、下一步改什么。
	 * 输出直推 TG（800 字内，无 Markdown 表格，手机可读）。
	 */
	public String explain(Autopsy a) {
		try {
			xyz.xingfeng.QuanForge.entity.AiConfig cfg = configService.getConfig();
			StringBuilder data = new StringBuilder();
			data.append(String.format(Locale.ROOT, "已结算: %d胜%d负（胜率%.0f%%）\n死因分布:\n",
					a.wins(), a.losses(), a.wins() * 100.0 / Math.max(1, a.wins() + a.losses())));
			a.taxonomy().forEach((cat, n) -> data.append(String.format(Locale.ROOT,
					"%s: %d 笔  例: %s\n", cat, n, a.examples().getOrDefault(cat, ""))));
			JSONObject body = new JSONObject()
					.put("model", cfg.getModel())
					.put("temperature", 0.3)
					.put("messages", new JSONArray()
							.put(new JSONObject().put("role", "system").put("content", """
									你是量化交易复盘教练。用户是 100 倍杠杆的超短线交易者，看得懂中文但看不懂统计表。
									把死因分布翻译成他能行动的结论：
									1) 用大白话解释每类死因是什么意思（一句话一类，带笔数与占比）
									2) 指出最大的钱漏在哪里（按"如果修好能多赚/少亏多少"排序）
									3) 给 2~3 条具体可改的建议（对应：REBASE换挡/持盈更久/少出手/研判改进）
									类别含义：LOSS-chop-stop=方向对但止损被噪音扫掉（价格后来到了止盈位）；
									LOSS-right-side-trend=方向本身就错（价格打掉止损后继续逆行）；
									LOSS-drift-flat=无方向震荡磨损；WIN-capped-early=止盈太早利润截断；
									WIN-clean=止盈即顶完美离场。
									要求：中文、口语化、直接、500字内、不要表格、不要客套。数字要具体。"""))
							.put(new JSONObject().put("role", "user").put("content", data.toString())));
			okhttp3.Request request = new okhttp3.Request.Builder()
					.url(cfg.getBaseUrl().replaceAll("/+$", "") + "/chat/completions")
					.header("Authorization", "Bearer " + cfg.getApiKey())
					.post(okhttp3.RequestBody.create(body.toString(),
							okhttp3.MediaType.parse("application/json; charset=utf-8")))
					.build();
			try (okhttp3.Response response = clients.obtain(xyz.xingfeng.QuanForge.client.ProxiedHttpClients.SLOW)
					.newCall(request).execute()) {
				String respBody = response.body() != null ? response.body().string() : "";
				if (!response.isSuccessful()) {
					throw new IllegalStateException("LLM HTTP " + response.code());
				}
				return new JSONObject(respBody).getJSONArray("choices").getJSONObject(0)
						.getJSONObject("message").optString("content", "").trim();
			}
		} catch (Exception e) {
			log.warn("验尸解读失败，退回原始分布: {}", e.getMessage());
			StringBuilder sb = new StringBuilder("== 验尸分布（解读失败）==\n");
			a.taxonomy().forEach((cat, n) -> sb.append(cat).append(": ").append(n).append("\n"));
			return sb.toString();
		}
	}

	/**
	 * 对最近 N 笔已结算单做死因分类（K 线重放）。
	 * N 限制在 40 以内：每单一次 kline 调用，避免长跑。
	 */
	public Autopsy autopsyRecent(int limit) {
		List<AiAdviceTrack> settled = repository.findAll().stream()
				.filter(t -> AiAdviceTrack.STATUS_WIN.equals(t.getStatus())
						|| AiAdviceTrack.STATUS_LOSS.equals(t.getStatus()))
				.sorted(java.util.Comparator.comparing(AiAdviceTrack::getId).reversed())
				.limit(Math.min(Math.max(limit, 10), 40))
				.toList();
		Map<String, Integer> tax = new java.util.LinkedHashMap<>();
		Map<String, String> ex = new java.util.HashMap<>();
		int wins = 0, losses = 0;
		java.util.Map<String, List<double[]>> cache = new java.util.HashMap<>();
		for (AiAdviceTrack t : settled) {
			String cat = classify(t, cache);
			tax.merge(cat, 1, Integer::sum);
			ex.computeIfAbsent(cat, k -> String.format(Locale.ROOT,
					"#%d %s %s %.2f%%", t.getId(), t.getSymbol(), t.getAction(),
					t.getResultPct() == null ? 0 : t.getResultPct()));
			if (cat.startsWith("WIN")) {
				wins++;
			} else {
				losses++;
			}
		}
		return new Autopsy(wins, losses, tax, ex);
	}

	/** 单笔分类：拉结算后 4h 的 1m K 线重放 */
	private String classify(AiAdviceTrack t, java.util.Map<String, List<double[]>> cache) {
		try {
			boolean buy = "BUY".equals(t.getAction());
			double entry = t.getActualEntry() != null ? t.getActualEntry() : t.getEntry();
			double sl = t.getStopLoss();
			double tp = t.getTakeProfit();
			long sinceMs = t.getEnteredAt() == null ? t.getCreatedAt()
					.atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli()
					: t.getEnteredAt().atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli();
			long settledMs = t.getSettledAt() == null ? sinceMs
					: t.getSettledAt().atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli();
			List<double[]> ks = cache.computeIfAbsent(t.getSymbol() + ":" + (sinceMs / 3600_000),
					k -> fetchKlines(t.getSymbol(), sinceMs, settledMs + 4 * 3600_000));
			double slDist = Math.abs(entry - sl) / entry * 100;
			double tpDist = Math.abs(tp - entry) / entry * 100;
			boolean win = AiAdviceTrack.STATUS_WIN.equals(t.getStatus());
			Double tpAfterMin = null;
			double ranPastTp = 0;
			double worstBeyond = 0;
			for (double[] k : ks) {
				long tm = (long) k[0];
				double high = k[1], low = k[2];
				if (tm > settledMs) {
					if (tpAfterMin == null && (buy ? high >= tp : low <= tp)) {
						tpAfterMin = (tm - settledMs) / 60_000.0;
					}
					double past = buy ? (high - tp) / tp * 100 : (tp - low) / tp * 100;
					ranPastTp = Math.max(ranPastTp, past);
				}
				double beyond = buy && low < sl ? (sl - low) / sl * 100
						: (!buy && high > sl ? (high - sl) / sl * 100 : 0);
				worstBeyond = Math.max(worstBeyond, beyond);
			}
			if (win) {
				return ranPastTp > tpDist * 0.5 ? "WIN-capped-early" : "WIN-clean";
			}
			if (tpAfterMin != null && tpAfterMin <= 240) {
				return "LOSS-chop-stop";
			}
			if (worstBeyond > slDist * 1.5) {
				return "LOSS-right-side-trend";
			}
			return "LOSS-drift-flat";
		} catch (Exception e) {
			log.warn("验尸失败 #{} {}: {}", t.getId(), t.getSymbol(), e.getMessage());
			return "UNKNOWN";
		}
	}

	private List<double[]> fetchKlines(String symbol, long startMs, long endMs) throws Exception {
		java.util.List<double[]> out = new java.util.ArrayList<>();
		long cur = startMs;
		while (cur < endMs) {
			String json = bybitService.getPublicRaw("/v5/market/kline",
					Map.of("category", "linear", "symbol", symbol, "interval", "1",
							"limit", "200", "start", String.valueOf(cur), "end", String.valueOf(endMs)));
			JSONArray list = new JSONObject(json).getJSONObject("result").getJSONArray("list");
			if (list.isEmpty()) {
				break;
			}
			java.util.List<double[]> rows = new java.util.ArrayList<>();
			for (int i = 0; i < list.length(); i++) {
				JSONArray k = list.getJSONArray(i);
				rows.add(new double[] { Double.parseDouble(k.getString(0)),
						Double.parseDouble(k.getString(2)), Double.parseDouble(k.getString(3)) });
			}
			rows.sort(java.util.Comparator.comparingDouble(r -> r[0]));
			out.addAll(rows.stream().filter(r -> r[0] >= cur).toList());
			cur = (long) rows.get(rows.size() - 1)[0] + 60_000;
		}
		return out;
	}
}
