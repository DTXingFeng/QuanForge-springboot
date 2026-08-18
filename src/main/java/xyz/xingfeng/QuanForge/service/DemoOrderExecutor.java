package xyz.xingfeng.QuanForge.service;

import org.json.JSONArray;
import org.json.JSONObject;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 模拟盘实单执行器：把 AI 建议变成 Bybit demo 账户上的真实委托。
 * <p>
 * 设计要点：
 * <ul>
 *   <li>入场用<b>限价单</b>挂在建议入场价（保真"回调入场"语义），TP/SL 随单附带，
 *       成交后由交易所管理——结算判定不依赖本地 K 线回放</li>
 *   <li>数量按 保证金占比 × 杠杆（取品种上限截断）计算，对齐 qtyStep/tickSize</li>
 *   <li>实际盈亏从 /v5/position/closed-pnl 读取（含滑点；模拟盘零手续费），
 *       这是"绝对准确"的记账来源</li>
 * </ul>
 * 研判逻辑（LLM × 双域模型共振）不在此层，本层只做忠实的执行与回报。
 */
@Service
public class DemoOrderExecutor {

	private static final Logger log = LoggerFactory.getLogger(DemoOrderExecutor.class);

	/** 下单成功的返回：委托 id + 实际数量 + 使用的权益快照 */
	public record Placement(String orderId, double qty, double equityUsd) {
	}

	/** 品种交易规格（下单量/价格对齐用） */
	public record Instrument(double minQty, double qtyStep, double minNotional,
			double maxLeverage, double tickSize) {
	}

	/** 平仓结果（closed-pnl 聚合） */
	public record ClosedResult(double pnl, double qty, double avgExit) {
	}

	private final BybitService bybit;

	public DemoOrderExecutor(BybitService bybit) {
		this.bybit = bybit;
	}

	// ==================== 下单 ====================

	/**
	 * 挂限价入场单（带 TP/SL）。
	 *
	 * @param action       BUY / SELL
	 * @param marginPct    保证金占账户比例（%）
	 * @param habitLeverage 惯用杠杆（会被品种上限截断）
	 */
	public Placement placeEntry(String symbol, String action, double entry, double tp, double sl,
			double marginPct, int habitLeverage) {
		Instrument inst = instrument(symbol);
		double equity = equityUsd();
		int lev = (int) Math.max(1, Math.min(habitLeverage, inst.maxLeverage()));
		double notional = equity * marginPct / 100.0 * lev;

		BigDecimal qty = floorToStep(notional / entry, inst.qtyStep());
		if (qty.compareTo(BigDecimal.valueOf(inst.minQty())) < 0) {
			qty = BigDecimal.valueOf(inst.minQty());
		}
		if (qty.doubleValue() * entry < inst.minNotional()) {
			throw new IllegalStateException(String.format(
					"%s 名义价值 %.2f 低于最小 %.2f，放弃下单", symbol,
					qty.doubleValue() * entry, inst.minNotional()));
		}

		// 杠杆与仓位模式预设置（幂等；已持仓位时报"未变更"类错误，忽略）
		setLeverage(symbol, lev);

		// 注意：不随单附带 TP/SL——Bybit 对挂单的 TP/SL 按下单瞬间的现价校验，
		// 回调入场型建议（entry 距现价较远）会被拒。改为成交后 trading-stop 设置。
		JSONObject body = new JSONObject();
		body.put("category", "linear");
		body.put("symbol", symbol);
		body.put("side", "BUY".equals(action) ? "Buy" : "Sell");
		body.put("orderType", "Limit");
		body.put("qty", plain(qty));
		body.put("price", plain(roundToTick(entry, inst.tickSize())));
		body.put("timeInForce", "GTC");
		body.put("orderLinkId", "qf-" + System.currentTimeMillis());

		JSONObject resp = new JSONObject(bybit.post(BybitService.DEFAULT_CREDENTIAL_NAME,
				"/v5/order/create", body.toString()));
		requireOk(resp, "下单");
		String orderId = resp.getJSONObject("result").optString("orderId", "");
		if (orderId.isEmpty()) {
			throw new IllegalStateException("下单成功但未返回 orderId");
		}
		log.info("模拟盘委托已挂: {} {} qty={} entry={} lev={}x margin={}%",
				symbol, action, plain(qty), body.getString("price"), lev, marginPct);
		return new Placement(orderId, qty.doubleValue(), equity);
	}

	/** 成交后设置持仓 TP/SL（tpslMode=Full，LastPrice 触发） */
	public void setTradingStop(String symbol, String action, double tp, double sl) {
		Instrument inst = instrument(symbol);
		JSONObject body = new JSONObject();
		body.put("category", "linear");
		body.put("symbol", symbol);
		body.put("takeProfit", plain(roundToTick(tp, inst.tickSize())));
		body.put("stopLoss", plain(roundToTick(sl, inst.tickSize())));
		body.put("tpslMode", "Full");
		body.put("tpTriggerBy", "LastPrice");
		body.put("slTriggerBy", "LastPrice");
		body.put("positionIdx", 0);
		JSONObject resp = new JSONObject(bybit.post(BybitService.DEFAULT_CREDENTIAL_NAME,
				"/v5/position/trading-stop", body.toString()));
		requireOk(resp, "设置TP/SL");
		log.info("模拟盘TP/SL已设: {} {} tp={} sl={}", symbol, action,
				body.getString("takeProfit"), body.getString("stopLoss"));
	}

	/** 市价平仓（reduceOnly） */
	public void marketClose(String symbol, String positionSide, double qty) {
		Instrument inst = instrument(symbol);
		BigDecimal q = floorToStep(qty, inst.qtyStep());
		if (q.doubleValue() <= 0) {
			return;
		}
		JSONObject body = new JSONObject();
		body.put("category", "linear");
		body.put("symbol", symbol);
		body.put("side", "Buy".equals(positionSide) ? "Sell" : "Buy");
		body.put("orderType", "Market");
		body.put("qty", plain(q));
		body.put("reduceOnly", true);
		JSONObject resp = new JSONObject(bybit.post(BybitService.DEFAULT_CREDENTIAL_NAME,
				"/v5/order/create", body.toString()));
		requireOk(resp, "市价平仓");
		log.info("模拟盘市价平仓: {} qty={}", symbol, plain(q));
	}

	/** 撤单 */
	public boolean cancel(String symbol, String orderId) {
		JSONObject body = new JSONObject()
				.put("category", "linear")
				.put("symbol", symbol)
				.put("orderId", orderId);
		JSONObject resp = new JSONObject(bybit.post(BybitService.DEFAULT_CREDENTIAL_NAME,
				"/v5/order/cancel", body.toString()));
		if (resp.optInt("retCode", -1) == 0) {
			return true;
		}
		// 订单已成交/已撤销时撤单会报错——不算失败
		log.info("撤单 {} 返回: {}（可能已成交/已撤销）", orderId, resp.optString("retMsg"));
		return false;
	}

	// ==================== 查询 ====================

	/** 账户总权益（USDT） */
	public double equityUsd() {
		JSONObject resp = new JSONObject(bybit.getUnifiedWalletBalance());
		requireOk(resp, "查余额");
		JSONArray list = resp.getJSONObject("result").getJSONArray("list");
		if (list.isEmpty()) {
			throw new IllegalStateException("钱包余额返回空");
		}
		String eq = list.getJSONObject(0).optString("totalEquity", "0");
		return Double.parseDouble(eq);
	}

	/**
	 * 委托状态：orderStatus New/PartiallyFilled/Filled/Cancelled + 累计成交与均价。
	 * <p>
	 * /v5/order/detail 在 demo 环境返回空体（实测），故用 history（终态单）+
	 * realtime（工作单）两段查询组合。
	 */
	public JSONObject orderDetail(String symbol, String orderId) {
		for (String endpoint : new String[] { "/v5/order/history", "/v5/order/realtime" }) {
			Map<String, String> params = new LinkedHashMap<>();
			params.put("category", "linear");
			params.put("symbol", symbol);
			params.put("orderId", orderId);
			JSONObject resp = new JSONObject(bybit.getRaw(BybitService.DEFAULT_CREDENTIAL_NAME,
					endpoint, params));
			if (resp.optInt("retCode", -1) != 0) {
				throw new IllegalStateException("查委托失败: " + resp.optString("retMsg"));
			}
			JSONArray list = resp.getJSONObject("result").optJSONArray("list");
			if (list != null && !list.isEmpty()) {
				return list.getJSONObject(0);
			}
		}
		throw new IllegalStateException("委托 " + orderId + " 在 history/realtime 均未找到");
	}

	/** 当前持仓：size/side/avgPrice；无仓位返回 null */
	public JSONObject position(String symbol) {
		Map<String, String> params = new LinkedHashMap<>();
		params.put("category", "linear");
		params.put("symbol", symbol);
		JSONObject resp = new JSONObject(bybit.getRaw(BybitService.DEFAULT_CREDENTIAL_NAME,
				"/v5/position/list", params));
		requireOk(resp, "查持仓");
		JSONArray list = resp.getJSONObject("result").optJSONArray("list");
		if (list == null || list.isEmpty()) {
			return null;
		}
		JSONObject p = list.getJSONObject(0);
		return Double.parseDouble(p.optString("size", "0")) <= 0 ? null : p;
	}

	/**
	 * 某时刻之后的平仓盈亏聚合：sum(closedPnl)、总量、加权出场价。
	 * 注意字段名是 closedPnl（Bybit v5 约定），曾误用 "pnl" 导致盈亏恒 0。
	 * 资金费率不计入 closed-pnl（单子生命周期短，多数不跨结算点，口径在复盘注明）。
	 */
	public ClosedResult closedPnlSince(String symbol, long sinceMs) {
		Map<String, String> params = new LinkedHashMap<>();
		params.put("category", "linear");
		params.put("symbol", symbol);
		params.put("limit", "50");
		params.put("startTime", String.valueOf(sinceMs - 60_000));
		JSONObject resp = new JSONObject(bybit.getRaw(BybitService.DEFAULT_CREDENTIAL_NAME,
				"/v5/position/closed-pnl", params));
		requireOk(resp, "查平仓盈亏");
		JSONArray list = resp.getJSONObject("result").optJSONArray("list");
		if (list == null) {
			return null;
		}
		double pnl = 0, qtySum = 0, exitNotional = 0;
		for (int i = 0; i < list.length(); i++) {
			JSONObject e = list.getJSONObject(i);
			if (e.optLong("createdTime", 0) < sinceMs - 60_000) {
				continue;
			}
			double q = Double.parseDouble(e.optString("closedSize", "0"));
			double exit = Double.parseDouble(e.optString("avgExitPrice", "0"));
			pnl += Double.parseDouble(e.optString("closedPnl", "0"));
			qtySum += q;
			exitNotional += q * exit;
		}
		return qtySum <= 0 ? null : new ClosedResult(pnl, qtySum, exitNotional / qtySum);
	}

	// ==================== 规格与工具 ====================

	/** 品种规格：最小量/步进/最小名义/最大杠杆/价格步进 */
	public Instrument instrument(String symbol) {
		JSONObject resp = new JSONObject(bybit.getPublicRaw("/v5/market/instruments-info",
				Map.of("category", "linear", "symbol", symbol)));
		requireOk(resp, "查品种规格");
		JSONArray list = resp.getJSONObject("result").getJSONArray("list");
		if (list.isEmpty()) {
			throw new IllegalStateException(symbol + " 无合约规格");
		}
		JSONObject i = list.getJSONObject(0);
		JSONObject lot = i.getJSONObject("lotSizeFilter");
		JSONObject price = i.getJSONObject("priceFilter");
		return new Instrument(
				Double.parseDouble(lot.getString("minOrderQty")),
				Double.parseDouble(lot.getString("qtyStep")),
				Double.parseDouble(lot.optString("minNotionalValue", "0")),
				Double.parseDouble(i.getJSONObject("leverageFilter").getString("maxLeverage")),
				Double.parseDouble(price.getString("tickSize")));
	}

	private void setLeverage(String symbol, int lev) {
		try {
			JSONObject body = new JSONObject()
					.put("category", "linear")
					.put("symbol", symbol)
					.put("buyLeverage", String.valueOf(lev))
					.put("sellLeverage", String.valueOf(lev));
			bybit.post(BybitService.DEFAULT_CREDENTIAL_NAME, "/v5/position/set-leverage",
					body.toString());
		} catch (Exception e) {
			log.debug("设置杠杆 {} {}x: {}", symbol, lev, e.getMessage());
		}
	}

	private void requireOk(JSONObject resp, String action) {
		if (resp.optInt("retCode", -1) != 0) {
			throw new IllegalStateException(action + "失败: " + resp.optString("retMsg")
					+ " (retCode=" + resp.optInt("retCode") + ")");
		}
	}

	/** 纯十进制 floor：Math.floor(v/step)*step 有浮点伪影（0.627→0.6000000000000001），Bybit 会拒单 */
	private static BigDecimal floorToStep(double value, double step) {
		if (step <= 0) {
			return BigDecimal.valueOf(value);
		}
		return BigDecimal.valueOf(value)
				.divide(BigDecimal.valueOf(step), 0, java.math.RoundingMode.FLOOR)
				.multiply(BigDecimal.valueOf(step));
	}

	private static BigDecimal roundToTick(double price, double tick) {
		if (tick <= 0) {
			return BigDecimal.valueOf(price);
		}
		return BigDecimal.valueOf(price)
				.divide(BigDecimal.valueOf(tick), 0, java.math.RoundingMode.HALF_UP)
				.multiply(BigDecimal.valueOf(tick));
	}

	private static String plain(BigDecimal v) {
		return v.stripTrailingZeros().toPlainString();
	}
}
