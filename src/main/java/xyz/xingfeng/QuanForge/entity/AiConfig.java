package xyz.xingfeng.QuanForge.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Convert;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import xyz.xingfeng.QuanForge.crypto.EncryptingConverter;

import java.time.LocalDateTime;

/**
 * AI 服务配置（全局单例，固定主键 1）：OpenAI 兼容接口 + 自动盯盘参数。
 * API Key 落库加密，读取解密。
 */
@Entity
@Table(name = "ai_config")
public class AiConfig {

	public static final long SINGLETON_ID = 1L;

	@Id
	private Long id;

	/** OpenAI 兼容基地址，如 https://api.openai.com/v1 */
	@Column(nullable = false, length = 256)
	private String baseUrl;

	/** API Key（落库加密） */
	@Column(name = "api_key", nullable = false, length = 512)
	@Convert(converter = EncryptingConverter.class)
	private String apiKey;

	/** 模型名，如 gpt-4o-mini / glm-4.6 / deepseek-chat */
	@Column(nullable = false, length = 64)
	private String model;

	/** 自动盯盘总开关 */
	@Column(nullable = false)
	private Boolean enabled = Boolean.FALSE;

	/** 盯盘品种（逗号分隔，如 BTCUSDT,ETHUSDT） */
	@Column(name = "watch_symbols", nullable = false, length = 256)
	private String watchSymbols = "BTCUSDT,ETHUSDT";

	/** 扫描间隔（分钟） */
	@Column(name = "scan_interval_minutes", nullable = false)
	private Integer scanIntervalMinutes = 10;

	/** 15 分钟涨跌幅异动阈值（%） */
	@Column(name = "change_threshold_pct", nullable = false)
	private Double changeThresholdPct = 2.0;

	/** 快讯关键词也触发分析 */
	@Column(name = "news_keyword_on", nullable = false)
	private Boolean newsKeywordOn = Boolean.TRUE;

	/** 惯用杠杆倍数（策略画像，供提示词使用） */
	@Column(nullable = false)
	private Integer leverage = 100;

	/** 出手门槛：预计短线单向变动幅度（%，需覆盖手续费） */
	@Column(name = "min_move_pct", nullable = false)
	private Double minMovePct = 0.1;

	/** 策略备注：用户补充的交易风格说明（注入提示词） */
	@Column(name = "strategy_note", nullable = false, length = 1000)
	private String strategyNote = "";

	/** 自动执行：BUY/SELL 建议在模拟盘真实下单，closed-pnl 真实记账 */
	@Column(name = "auto_order_enabled", nullable = false)
	private Boolean autoOrderEnabled = Boolean.FALSE;

	/** 自动执行每单保证金占账户比例（%） */
	@Column(name = "auto_margin_pct", nullable = false)
	private Double autoMarginPct = 5.0;

	/** 自动执行首次开启时的账户权益基线（"重置资金前"的分界线，USDT） */
	@Column(name = "equity_baseline")
	private Double equityBaseline;

	@Column(name = "equity_baseline_at")
	private LocalDateTime equityBaselineAt;

	/** 创建时间 */
	@Column(name = "created_at", updatable = false)
	private LocalDateTime createdAt;

	/** 更新时间 */
	@Column(name = "updated_at")
	private LocalDateTime updatedAt;

	@PrePersist
	void onCreate() {
		LocalDateTime now = LocalDateTime.now();
		this.createdAt = now;
		this.updatedAt = now;
	}

	@PreUpdate
	void onUpdate() {
		this.updatedAt = LocalDateTime.now();
	}

	public Long getId() {
		return id;
	}

	public void setId(Long id) {
		this.id = id;
	}

	public String getBaseUrl() {
		return baseUrl;
	}

	public void setBaseUrl(String baseUrl) {
		this.baseUrl = baseUrl;
	}

	public String getApiKey() {
		return apiKey;
	}

	public void setApiKey(String apiKey) {
		this.apiKey = apiKey;
	}

	public String getModel() {
		return model;
	}

	public void setModel(String model) {
		this.model = model;
	}

	public Boolean getEnabled() {
		return enabled;
	}

	public void setEnabled(Boolean enabled) {
		this.enabled = enabled;
	}

	public String getWatchSymbols() {
		return watchSymbols;
	}

	public void setWatchSymbols(String watchSymbols) {
		this.watchSymbols = watchSymbols;
	}

	public Integer getScanIntervalMinutes() {
		return scanIntervalMinutes;
	}

	public void setScanIntervalMinutes(Integer scanIntervalMinutes) {
		this.scanIntervalMinutes = scanIntervalMinutes;
	}

	public Double getChangeThresholdPct() {
		return changeThresholdPct;
	}

	public void setChangeThresholdPct(Double changeThresholdPct) {
		this.changeThresholdPct = changeThresholdPct;
	}

	public Boolean getNewsKeywordOn() {
		return newsKeywordOn;
	}

	public void setNewsKeywordOn(Boolean newsKeywordOn) {
		this.newsKeywordOn = newsKeywordOn;
	}

	public Integer getLeverage() {
		return leverage;
	}

	public void setLeverage(Integer leverage) {
		this.leverage = leverage;
	}

	public Double getMinMovePct() {
		return minMovePct;
	}

	public void setMinMovePct(Double minMovePct) {
		this.minMovePct = minMovePct;
	}

	public String getStrategyNote() {
		return strategyNote;
	}

	public void setStrategyNote(String strategyNote) {
		this.strategyNote = strategyNote;
	}

	public Boolean getAutoOrderEnabled() {
		return autoOrderEnabled;
	}

	public void setAutoOrderEnabled(Boolean autoOrderEnabled) {
		this.autoOrderEnabled = autoOrderEnabled;
	}

	public Double getAutoMarginPct() {
		return autoMarginPct;
	}

	public void setAutoMarginPct(Double autoMarginPct) {
		this.autoMarginPct = autoMarginPct;
	}

	public Double getEquityBaseline() {
		return equityBaseline;
	}

	public void setEquityBaseline(Double equityBaseline) {
		this.equityBaseline = equityBaseline;
	}

	public LocalDateTime getEquityBaselineAt() {
		return equityBaselineAt;
	}

	public void setEquityBaselineAt(LocalDateTime equityBaselineAt) {
		this.equityBaselineAt = equityBaselineAt;
	}

	/**
	 * 策略画像文本块：注入 LLM 提示词，让研判贴合用户风格（剥头皮/杠杆/损失可控）。
	 * agentic 与固定上下文两条路径共用，避免两处口径漂移。
	 * 核心哲学：出手宽松（空仓也是成本），但每单必须带结构位止损——损失可控优先于高确定性。
	 */
	public String strategyPromptBlock() {
		int lev = leverage == null ? 100 : leverage;
		double minMove = minMovePct == null ? 0.1 : minMovePct;
		StringBuilder sb = new StringBuilder();
		sb.append(String.format(java.util.Locale.ROOT, """
				用户策略画像（建议必须贴合）：
				- 风格：超短线，惯用杠杆 %d 倍；单笔持仓数分钟到数小时，用户会亲自动态管理（转弱及时收手 / 有反弹逻辑则持有甚至加仓）。
				- 出手哲学：损失可控优先于高确定性。只要方向倾向成立（趋势、结构、动能一致）\
			 即可输出 BUY/SELL，不要因"把握不足"过度观望——空仓错过也是成本；\
			 但每次出手必须带明确止损。
				- 止损（必须给）：放在结构失效位之外（近期高低点、布林另一侧、约 1~1.5×ATR）。
				- 仓位纪律（重要）：用户使用**全仓（cross）模式但从不 all in**——\
			 每次只用账户一小部分资金开仓，全账户做背书换取极远的强平价。\
			 每条 BUY/SELL 建议必须在 detail 中给出：建议保证金占账户比例（通常 5%%~20%%）\
			 与止损对应的**账户级最大亏损 %%**。换算：账户风险%% = 实际杠杆 × 保证金占比 × 止损距离%%。\
			 **实际杠杆 = min(惯用 %d 倍, 品种最大杠杆)**——山寨币上限常为 12.5/25/75，\
			 必须先调 get_instrument 查品种上限再计算，用错杠杆的建议视为无效。\
			 目标单笔账户风险 ≤ 1%%，宁可小仓多次，不可重仓一搏。
				- 止盈（弹性）：给最近的第一目标位即可（前高/前低、布林另一侧），\
			 距入场 ≥ %.2f%%（覆盖 taker 往返约 0.11%% 手续费）；\
			 可补充动态管理预案：跌破哪里说明判断失效应离场，守住哪里可持有甚至加仓。
				- 盈亏换算：实际杠杆（品种上限截断后）下价格每变动 0.10%%，\
			 若保证金占比 10%% 则账户权益变动约 实际杠杆×0.01%%。
				- 周期：以 1m/5m K 线定方向与入场，15m/1h 只作趋势过滤，\
			 严禁只看大周期给短线建议。""", lev, lev, minMove));
		if (strategyNote != null && !strategyNote.isBlank()) {
			sb.append("\n- 用户补充要求：").append(strategyNote.trim());
		}
		return sb.toString();
	}

	public LocalDateTime getCreatedAt() {
		return createdAt;
	}

	public LocalDateTime getUpdatedAt() {
		return updatedAt;
	}
}
