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
 *   <li>平仓盈亏从 /v5/position/closed-pnl 读取；必须另行核对手续费、资金费与订单归属，
 *       当前时间窗聚合不等同逐单完整账本</li>
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
		return placeEntry(symbol, action, entry, tp, sl, marginPct, habitLeverage,
				"qf-" + java.util.UUID.randomUUID().toString().replace("-", ""));
	}

	public Placement placeEntry(String symbol, String action, double entry, double tp, double sl,
			double marginPct, int habitLeverage, String orderLinkId) {
		if (orderLinkId == null || !orderLinkId.matches("[A-Za-z0-9_-]{1,36}")) {
			throw new IllegalArgumentException("必须提供已持久化的订单编号");
		}
		if (!("BUY".equals(action) || "SELL".equals(action))
				|| !Double.isFinite(entry) || !Double.isFinite(tp) || !Double.isFinite(sl)
				|| entry <= 0 || tp <= 0 || sl <= 0 || !Double.isFinite(marginPct)
				|| marginPct <= 0 || marginPct > 100 || habitLeverage < 1
				|| !("BUY".equals(action) ? sl < entry && entry < tp : tp < entry && entry < sl)) {
			throw new IllegalArgumentException("非法入场方向、价位或仓位预算");
		}
		Instrument inst = instrument(symbol);
		double equity = equityUsd();
		int lev = (int) Math.max(1, Math.min(habitLeverage, inst.maxLeverage()));
		double notional = equity * marginPct / 100.0 * lev;

		BigDecimal qty = floorToStep(notional / entry, inst.qtyStep());
		if (qty.compareTo(BigDecimal.valueOf(inst.minQty())) < 0) {
			throw new IllegalStateException("预算不足最小下单量，禁止向上扩大仓位");
		}
		if (qty.doubleValue() * entry < inst.minNotional()) {
			throw new IllegalStateException(String.format(
					"%s 名义价值 %.2f 低于最小 %.2f，放弃下单", symbol,
					qty.doubleValue() * entry, inst.minNotional()));
		}

		// 杠杆与仓位模式预设置（幂等；已持仓位时报"未变更"类错误，忽略）
		setLeverage(symbol, lev);

		// 急动即时入场：entry 距现价 <0.15% 时改市价单——趋势启动时等限价成交
		// 平均滞后 0~3 分钟（实测），市价立刻上车
		double last = lastPriceOf(symbol);
		boolean immediate = Math.abs(entry - last) / last < 0.0015;
		String orderType = "Limit";
		if (immediate) {
			orderType = "Market";
		}
		JSONObject body = new JSONObject();
		body.put("category", "linear");
		body.put("symbol", symbol);
		body.put("side", "BUY".equals(action) ? "Buy" : "Sell");
		body.put("orderType", orderType);
		body.put("qty", plain(qty));
		if (!immediate) {
			body.put("price", plain(roundToTick(entry, inst.tickSize())));
			body.put("timeInForce", "GTC");
		}
		// Never submit an unprotected entry. Exchange rejection leaves no naked fallback order.
		body.put("takeProfit", plain(roundToTick(tp, inst.tickSize())));
		body.put("stopLoss", plain(roundToTick(sl, inst.tickSize())));
		body.put("tpslMode", "Full");
		body.put("tpTriggerBy", "LastPrice");
		body.put("slTriggerBy", "LastPrice");
		body.put("positionIdx", 0);
		body.put("orderLinkId", orderLinkId);

		JSONObject resp = new JSONObject(bybit.postDemo(BybitService.DEFAULT_CREDENTIAL_NAME,
				"/v5/order/create", body.toString()));
		requireOk(resp, "下单");
		String orderId = resp.getJSONObject("result").optString("orderId", "");
		if (orderId.isEmpty()) {
			throw new IllegalStateException("下单成功但未返回 orderId");
		}
		log.info("模拟盘委托已挂: {} {} {} qty={} entry={} lev={}x margin={}%",
				symbol, action, orderType, plain(qty),
				immediate ? String.format("%.4f(last)", last) : body.getString("price"),
				lev, marginPct);
		return new Placement(orderId, qty.doubleValue(), equity);
	}

	/** 最新成交价（内部工具，失败抛异常） */
	private double lastPriceOf(String symbol) {
		JSONObject resp = new JSONObject(bybit.getPublicRaw("/v5/market/tickers",
				java.util.Map.of("category", "linear", "symbol", symbol)));
		JSONArray list = resp.getJSONObject("result").getJSONArray("list");
		if (list.isEmpty()) {
			throw new IllegalStateException(symbol + " 无行情");
		}
		return Double.parseDouble(list.getJSONObject(0).getString("lastPrice"));
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
		JSONObject resp = new JSONObject(bybit.postDemo(BybitService.DEFAULT_CREDENTIAL_NAME,
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
		JSONObject resp = new JSONObject(bybit.postDemo(BybitService.DEFAULT_CREDENTIAL_NAME,
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
		JSONObject resp = new JSONObject(bybit.postDemo(BybitService.DEFAULT_CREDENTIAL_NAME,
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
		JSONObject resp = new JSONObject(bybit.getDemoRaw(BybitService.DEFAULT_CREDENTIAL_NAME, "/v5/account/wallet-balance", Map.of("accountType", "UNIFIED")));
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
		return findOrder(symbol, "orderId", orderId);
	}

	/** Absence is not proof of rejection; callers must retain the unresolved intent. */
	public JSONObject orderDetailByLink(String symbol, String orderLinkId) {
		return findOrder(symbol, "orderLinkId", orderLinkId);
	}

	private JSONObject findOrder(String symbol, String identityField, String identity) {
		if (identity == null || identity.isBlank()) throw new IllegalArgumentException("缺少订单身份");
		for (String endpoint : new String[] { "/v5/order/history", "/v5/order/realtime" }) {
			Map<String, String> params = new LinkedHashMap<>();
			params.put("category", "linear");
			params.put("symbol", symbol);
			params.put(identityField, identity);
			JSONObject resp = new JSONObject(bybit.getDemoRaw(BybitService.DEFAULT_CREDENTIAL_NAME,
					endpoint, params));
			if (resp.optInt("retCode", -1) != 0) {
				throw new IllegalStateException("查委托失败: " + resp.optString("retMsg"));
			}
			JSONArray list = resp.getJSONObject("result").optJSONArray("list");
			if (list != null && !list.isEmpty()) {
				for (int i = 0; i < list.length(); i++) {
					JSONObject order = list.getJSONObject(i);
					if (identity.equals(order.optString(identityField)) && symbol.equals(order.optString("symbol"))) {
						return order;
					}
				}
			}
		}
		throw new IllegalStateException("委托在 history/realtime 均未确认，保留未知意图");
	}

	/** 当前持仓：size/side/avgPrice；无仓位返回 null */
	public JSONObject position(String symbol) {
		Map<String, String> params = new LinkedHashMap<>();
		params.put("category", "linear");
		params.put("symbol", symbol);
		JSONObject resp = new JSONObject(bybit.getDemoRaw(BybitService.DEFAULT_CREDENTIAL_NAME,
				"/v5/position/list", params));
		requireOk(resp, "查持仓");
		JSONArray list = resp.getJSONObject("result").optJSONArray("list");
		if (list == null || list.isEmpty()) {
			return null;
		}
		JSONObject p = list.getJSONObject(0);
		return Double.parseDouble(p.optString("size", "0")) <= 0 ? null : p;
	}

	/** 全部 USDT 线性持仓（孤儿巡检用） */
	public JSONArray positionsUsdt() {
		Map<String, String> params = new LinkedHashMap<>();
		params.put("category", "linear");
		params.put("settleCoin", "USDT");
		JSONObject resp = new JSONObject(bybit.getDemoRaw(BybitService.DEFAULT_CREDENTIAL_NAME,
				"/v5/position/list", params));
		requireOk(resp, "查全部持仓");
		JSONArray list = resp.getJSONObject("result").optJSONArray("list");
		return list == null ? new JSONArray() : list;
	}

	/** 只设保护性止损，不动 TP（trading-stop 省略字段=保持不变） */
	public void setProtectiveStop(String symbol, double sl) {
		Instrument inst = instrument(symbol);
		JSONObject body = new JSONObject();
		body.put("category", "linear");
		body.put("symbol", symbol);
		body.put("stopLoss", plain(roundToTick(sl, inst.tickSize())));
		body.put("tpslMode", "Full");
		body.put("slTriggerBy", "LastPrice");
		body.put("positionIdx", 0);
		JSONObject resp = new JSONObject(bybit.postDemo(BybitService.DEFAULT_CREDENTIAL_NAME,
				"/v5/position/trading-stop", body.toString()));
		requireOk(resp, "设保护性止损");
		log.info("保护性止损已设: {} sl={}", symbol, body.getString("stopLoss"));
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
		JSONObject resp = new JSONObject(bybit.getDemoRaw(BybitService.DEFAULT_CREDENTIAL_NAME,
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
			bybit.postDemo(BybitService.DEFAULT_CREDENTIAL_NAME, "/v5/position/set-leverage",
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
