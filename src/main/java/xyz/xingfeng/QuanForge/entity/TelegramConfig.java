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
 * Telegram 机器人配置（全局单例，固定主键 1）：
 * 长轮询接收指令 + 告警推送，让用户在任意网络环境（手机/公司网）操作工作站。
 * botToken 落库加密；chatId 即白名单——仅响应该会话的指令。
 */
@Entity
@Table(name = "telegram_config")
public class TelegramConfig {

	public static final long SINGLETON_ID = 1L;

	@Id
	private Long id;

	/** BotFather 颁发的 token（落库加密） */
	@Column(nullable = false, length = 256)
	@Convert(converter = EncryptingConverter.class)
	private String botToken = "";

	/** 授权会话 id：首次 /start 自动捕获；为空表示未绑定 */
	@Column(nullable = false, length = 32)
	private String chatId = "";

	/** 总开关（轮询与推送的总闸） */
	@Column(nullable = false)
	private Boolean enabled = Boolean.FALSE;

	@Column(name = "created_at", updatable = false)
	private LocalDateTime createdAt;

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

	public String getBotToken() {
		return botToken;
	}

	public void setBotToken(String botToken) {
		this.botToken = botToken;
	}

	public String getChatId() {
		return chatId;
	}

	public void setChatId(String chatId) {
		this.chatId = chatId;
	}

	public Boolean getEnabled() {
		return enabled;
	}

	public void setEnabled(Boolean enabled) {
		this.enabled = enabled;
	}

	public LocalDateTime getCreatedAt() {
		return createdAt;
	}

	public LocalDateTime getUpdatedAt() {
		return updatedAt;
	}
}
