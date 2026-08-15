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
 * AI 盯盘告警记录：一次异动触发的模型研判结果。
 */
@Entity
@Table(name = "ai_alert")
public class AiAlert {

	/** 告警等级 */
	public static final String LEVEL_INFO = "INFO";
	public static final String LEVEL_WARN = "WARN";
	public static final String LEVEL_CRITICAL = "CRITICAL";

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	/** 品种，如 BTCUSDT */
	@Column(nullable = false, length = 32)
	private String symbol;

	/** 等级：INFO / WARN / CRITICAL */
	@Column(nullable = false, length = 16)
	private String level;

	/** 标题（≤40 字） */
	@Column(nullable = false, length = 128)
	private String title;

	/** 摘要（≤120 字） */
	@Column(nullable = false, length = 256)
	private String summary;

	/** 详情分析 */
	@Column(nullable = false, length = 4096)
	private String detail;

	/** 触发原因（本地异动检测的描述，或 MANUAL） */
	@Column(name = "trigger_reason", nullable = false, length = 256)
	private String trigger;

	/** 模型置信度 0-100 */
	@Column
	private Integer confidence;

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

	public String getSymbol() {
		return symbol;
	}

	public void setSymbol(String symbol) {
		this.symbol = symbol;
	}

	public String getLevel() {
		return level;
	}

	public void setLevel(String level) {
		this.level = level;
	}

	public String getTitle() {
		return title;
	}

	public void setTitle(String title) {
		this.title = title;
	}

	public String getSummary() {
		return summary;
	}

	public void setSummary(String summary) {
		this.summary = summary;
	}

	public String getDetail() {
		return detail;
	}

	public void setDetail(String detail) {
		this.detail = detail;
	}

	public String getTrigger() {
		return trigger;
	}

	public void setTrigger(String trigger) {
		this.trigger = trigger;
	}

	public Integer getConfidence() {
		return confidence;
	}

	public void setConfidence(Integer confidence) {
		this.confidence = confidence;
	}

	public LocalDateTime getCreatedAt() {
		return createdAt;
	}
}
