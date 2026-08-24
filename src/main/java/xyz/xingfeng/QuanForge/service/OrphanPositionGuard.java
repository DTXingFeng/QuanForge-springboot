package xyz.xingfeng.QuanForge.service;

import org.json.JSONArray;
import org.json.JSONObject;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.Locale;

/**
 * v4.8.5 孤儿仓位兜底巡检：每 5 分钟扫一遍实盘持仓，
 * 发现 size&gt;0 且 TP/SL 双空的仓位 → 自动设保本止损 + TG 告警。
 * <p>
 * 背景：2026-08-21 ETHUSDT 孤儿仓位——委托成交后跟踪行写入 SQLITE_BUSY 失败，
 * 无人设 TP/SL，100x 杠杆裸奔 3 天（靠运气浮盈）。任何"成交了但没人管"的路径
 * （写库失败 / 进程崩溃 / 重启丢状态 / 网络中断在链路中间）都由此兜底。
 * <p>
 * 判定口径：takeProfit 与 stopLoss 均为空或 0 才动手（tracker 正常管理的仓位
 * 两者同设；巡检先设的保本 SL 会被 tracker 随后的正式 TP/SL 覆盖，无冲突）。
 */
@Component
public class OrphanPositionGuard {
	private static final Logger log = LoggerFactory.getLogger(OrphanPositionGuard.class);

	private final DemoOrderExecutor executor;
	private final TelegramBotService telegram;

	public OrphanPositionGuard(DemoOrderExecutor executor, TelegramBotService telegram) {
		this.executor = executor;
		this.telegram = telegram;
	}

	@Scheduled(fixedDelay = 300_000, initialDelay = 180_000)
	public void sweep() {
		JSONArray list;
		try {
			list = executor.positionsUsdt();
		} catch (Exception e) {
			log.warn("孤儿巡检查持仓失败(下轮重试): {}", e.getMessage());
			return;
		}
		for (int i = 0; i < list.length(); i++) {
			JSONObject p = list.getJSONObject(i);
			if (Double.parseDouble(p.optString("size", "0")) <= 0) {
				continue;
			}
			String symbol = p.optString("symbol", "");
			if (isSet(p.optString("takeProfit", "")) || isSet(p.optString("stopLoss", ""))) {
				continue;
			}
			double avg = Double.parseDouble(p.optString("avgPrice", "0"));
			double mark = Double.parseDouble(p.optString("markPrice", "0"));
			String side = p.optString("side", "?");
			String qty = p.optString("size", "?");
			double upl = Double.parseDouble(p.optString("unrealisedPnl", "0"));
			// 保本止损必须对现价合法: 买单 SL < last, 卖单 SL > last。
			// 实测 2026-08-24 SOL: 均价 94.17 但现价已跌到 94.12, 设 94.17 被 Bybit 拒
			// (retCode=10001)。取 均价与标记价 的保守侧再留 0.3% 缓冲。
			boolean buy = "Buy".equals(side);
			double ref = buy ? Math.min(avg, mark > 0 ? mark : avg)
					: Math.max(avg, mark > 0 ? mark : avg);
			double sl = buy ? ref * 0.997 : ref * 1.003;
			try {
				executor.setProtectiveStop(symbol, sl);
				log.warn("孤儿仓位已保护: {} {} qty={} entry={} upl={} -> SL={}",
						symbol, side, qty, avg, upl, String.format(Locale.ROOT, "%.6g", sl));
				telegram.send(String.format(Locale.ROOT,
						"🛡️ 孤儿仓位兜底: %s %s qty=%s entry=%.6g 浮盈=%.2f\n"
								+ "TP/SL 双空（跟踪链路曾断裂），已设保护性止损 SL=%.6g\n"
								+ "请人工确认该仓位归属",
						symbol, side, qty, avg, upl, sl));
			} catch (Exception e) {
				log.error("孤儿仓位保护失败 {}: {}", symbol, e.getMessage());
				telegram.send(String.format(Locale.ROOT,
						"🚨 孤儿仓位保护失败: %s %s qty=%s TP/SL双空，设保护性止损报错: %s\n"
								+ "下轮巡检自动重试; 若持续失败请立即人工处理!",
						symbol, side, qty, e.getMessage()));
			}
		}
	}

	private boolean isSet(String v) {
		if (v == null || v.isEmpty()) {
			return false;
		}
		try {
			return Double.parseDouble(v) > 0;
		} catch (NumberFormatException e) {
			return false;
		}
	}
}
