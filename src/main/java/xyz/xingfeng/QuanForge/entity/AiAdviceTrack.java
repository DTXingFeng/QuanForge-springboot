package xyz.xingfeng.QuanForge.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.Table;

import java.time.LocalDateTime;

/**
 * AI 建议纸面跟踪：带价位的 BUY/SELL 建议发出后，用 1m K 线自动验证盈亏。
 * 生命周期：PENDING（等价格触及入场）→ TRACKING（已入场，盯 TP/SL）→ WIN/LOSS/EXPIRED。
 * 这是评估 AI 建议质量（胜率/盈亏比）的唯一客观数据，不涉及真实下单。
 */
@Entity
@Table(name = "ai_advice_track")
public class AiAdviceTrack {

	public static final String STATUS_PENDING = "PENDING";
	public static final String STATUS_TRACKING = "TRACKING";
	public static final String STATUS_WIN = "WIN";
	public static final String STATUS_LOSS = "LOSS";
	public static final String STATUS_EXPIRED = "EXPIRED";

	/** 未入场等待上限：超时未触及入场价视为失效 */
	public static final int PENDING_TTL_MINUTES = 120;

	/** 持仓跟踪上限（剥头皮口径）：超时未触发 TP/SL 按过期结算 */
	public static final int TRACKING_TTL_MINUTES = 120;

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	/** 关联告警 id */
	@Column(name = "alert_id", nullable = false)
	private Long alertId;

	/** 品种，如 BTCUSDT */
	@Column(nullable = false, length = 32)
	private String symbol;

	/** 方向：BUY / SELL */
	@Column(nullable = false, length = 8)
	private String action;

	/** 建议入场价 */
	@Column(nullable = false)
	private Double entry;

	/** 建议止损价 */
	@Column(name = "stop_loss", nullable = false)
	private Double stopLoss;

	/** 建议止盈价 */
	@Column(name = "take_profit", nullable = false)
	private Double takeProfit;

	/** 状态：PENDING / TRACKING / WIN / LOSS / EXPIRED */
	@Column(nullable = false, length = 16)
	private String status = STATUS_PENDING;

	/** 实际入场时间（价格触及入场价后） */
	@Column(name = "entered_at")
	private LocalDateTime enteredAt;

	/** 结算时间 */
	@Column(name = "settled_at")
	private LocalDateTime settledAt;

	/** 结算时有利方向的价格变动 %（WIN 为正，LOSS 为负，EXPIRED 为结算时刻浮动） */
	@Column(name = "result_pct")
	private Double resultPct;

	/** 备注：TTL 超时 / 被新建议取代 / 同根K线双触发保守判损 等 */
	@Column(length = 128)
	private String note;

	/** 体系版本戳：建议产生时的研判体系（复盘按此分组，避免跨版本污染） */
	@Column(name = "sys_version", length = 32)
	private String sysVersion;

	/** 创建时间 */
	@Column(name = "created_at", updatable = false)
	private LocalDateTime createdAt;

	@PrePersist
	void onCreate() {
		this.createdAt = LocalDateTime.now();
	}

	public Long getId() {
		return id;
	}

	public Long getAlertId() {
		return alertId;
	}

	public void setAlertId(Long alertId) {
		this.alertId = alertId;
	}

	public String getSymbol() {
		return symbol;
	}

	public void setSymbol(String symbol) {
		this.symbol = symbol;
	}

	public String getAction() {
		return action;
	}

	public void setAction(String action) {
		this.action = action;
	}

	public Double getEntry() {
		return entry;
	}

	public void setEntry(Double entry) {
		this.entry = entry;
	}

	public Double getStopLoss() {
		return stopLoss;
	}

	public void setStopLoss(Double stopLoss) {
		this.stopLoss = stopLoss;
	}

	public Double getTakeProfit() {
		return takeProfit;
	}

	public void setTakeProfit(Double takeProfit) {
		this.takeProfit = takeProfit;
	}

	public String getStatus() {
		return status;
	}

	public void setStatus(String status) {
		this.status = status;
	}

	public LocalDateTime getEnteredAt() {
		return enteredAt;
	}

	public void setEnteredAt(LocalDateTime enteredAt) {
		this.enteredAt = enteredAt;
	}

	public LocalDateTime getSettledAt() {
		return settledAt;
	}

	public void setSettledAt(LocalDateTime settledAt) {
		this.settledAt = settledAt;
	}

	public Double getResultPct() {
		return resultPct;
	}

	public void setResultPct(Double resultPct) {
		this.resultPct = resultPct;
	}

	public String getNote() {
		return note;
	}

	public void setNote(String note) {
		this.note = note;
	}

	public String getSysVersion() {
		return sysVersion;
	}

	public void setSysVersion(String sysVersion) {
		this.sysVersion = sysVersion;
	}

	public LocalDateTime getCreatedAt() {
		return createdAt;
	}
}
