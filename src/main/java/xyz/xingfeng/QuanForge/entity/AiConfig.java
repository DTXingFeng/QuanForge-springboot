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

	/**
	 * 策略画像文本块：注入 LLM 提示词，让研判贴合用户风格（剥头皮/杠杆/出手门槛）。
	 * agentic 与固定上下文两条路径共用，避免两处口径漂移。
	 */
	public String strategyPromptBlock() {
		int lev = leverage == null ? 100 : leverage;
		double minMove = minMovePct == null ? 0.1 : minMovePct;
		StringBuilder sb = new StringBuilder();
		sb.append(String.format(java.util.Locale.ROOT, """
				用户策略画像（建议必须贴合）：
				- 风格：超短线剥头皮，惯用杠杆 %d 倍；单笔预期持仓数分钟到半小时。
				- 出手门槛：仅当判断未来 5~30 分钟价格单向变动概率较高、\
				且预计幅度 ≥ %.2f%%（覆盖手续费，用户以此决定是否出手）时才输出 BUY/SELL；\
				把握不足或预期幅度低于门槛时一律输出 HOLD。
				- 手续费与盈亏：taker 往返约 0.11%% 名义本金；%d 倍杠杆下价格每变动 0.10%% \
				对应保证金盈亏约 %.0f%%，止损不紧凑会迅速放大亏损。
				- 止盈止损：紧凑且具体——止损距入场约 0.1%%~0.4%%，止盈距入场 ≥ %.2f%%，\
				用 1m/5m 支撑阻力位或 ATR 定位，禁止给宽泛区间。
				- 周期：以 1m/5m K 线定方向与入场，15m/1h 只作趋势过滤，\
				严禁只看大周期给短线建议。""", lev, minMove, lev, lev * 0.1, minMove));
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
