package xyz.xingfeng.QuanForge.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Convert;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import xyz.xingfeng.QuanForge.crypto.EncryptingConverter;

import java.time.LocalDateTime;

/**
 * API 凭证实体：存储 apiKey 与 apiSecret。
 */
@Entity
@Table(name = "api_credential")
public class ApiCredential {

	/** 主键，自增 */
	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	/** 凭证标识，例如平台名（openai、anthropic 等），用于区分多套凭证 */
	@Column(nullable = false, unique = true, length = 64)
	private String name;

	/** API Key（落库加密，读取解密） */
	@Column(name = "api_key", nullable = false, length = 512)
	@Convert(converter = EncryptingConverter.class)
	private String apiKey;

	/** API Secret（落库加密，读取解密） */
	@Column(name = "api_secret", nullable = false, length = 1024)
	@Convert(converter = EncryptingConverter.class)
	private String apiSecret;

	/** 创建时间 */
	@Column(name = "created_at", updatable = false)
	private LocalDateTime createdAt;

	/** 更新时间 */
	@Column(name = "updated_at")
	private LocalDateTime updatedAt;

	/** 插入前填充时间 */
	@PrePersist
	void onCreate() {
		LocalDateTime now = LocalDateTime.now();
		this.createdAt = now;
		this.updatedAt = now;
	}

	/** 更新前刷新更新时间 */
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

	public String getName() {
		return name;
	}

	public void setName(String name) {
		this.name = name;
	}

	public String getApiKey() {
		return apiKey;
	}

	public void setApiKey(String apiKey) {
		this.apiKey = apiKey;
	}

	public String getApiSecret() {
		return apiSecret;
	}

	public void setApiSecret(String apiSecret) {
		this.apiSecret = apiSecret;
	}

	public LocalDateTime getCreatedAt() {
		return createdAt;
	}

	public void setCreatedAt(LocalDateTime createdAt) {
		this.createdAt = createdAt;
	}

	public LocalDateTime getUpdatedAt() {
		return updatedAt;
	}

	public void setUpdatedAt(LocalDateTime updatedAt) {
		this.updatedAt = updatedAt;
	}
}
