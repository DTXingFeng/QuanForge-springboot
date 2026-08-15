package xyz.xingfeng.QuanForge.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Convert;
import jakarta.persistence.Entity;
import jakarta.persistence.Enumerated;
import jakarta.persistence.EnumType;
import jakarta.persistence.Id;
import jakarta.persistence.PrePersist;
import jakarta.persistence.PreUpdate;
import jakarta.persistence.Table;
import xyz.xingfeng.QuanForge.crypto.EncryptingConverter;

import java.time.LocalDateTime;

/**
 * 代理配置实体：全局唯一（固定主键 SINGLETON_ID），保存 OkHttp 所需代理参数。
 * 代理只需保存一个，故用固定主键强制单例。
 */
@Entity
@Table(name = "proxy_config")
public class ProxyConfig {

	/** 单例固定主键，保证全表仅一条记录 */
	public static final Long SINGLETON_ID = 1L;

	@Id
	private Long id;

	/** 代理类型：HTTP / SOCKS */
	@Enumerated(EnumType.STRING)
	@Column(nullable = false, length = 16)
	private ProxyType type;

	/** 代理主机地址 */
	@Column(nullable = false, length = 256)
	private String host;

	/** 代理端口 */
	@Column(nullable = false)
	private Integer port;

	/** 代理认证用户名（可选，无认证时为空） */
	@Column(length = 128)
	private String username;

	/** 代理认证密码（可选，落库加密，读取解密） */
	@Column(length = 512)
	@Convert(converter = EncryptingConverter.class)
	private String password;

	/** 是否启用此代理（关闭时 OkHttp 直连） */
	@Column(nullable = false)
	private Boolean enabled = false;

	/**
	 * 代理是否也应用于 AI / 快讯请求（Bybit 请求始终遵循 enabled）。
	 * 关闭后 AI 与快讯全部直连——适用于 AI 用国内服务（智谱/DeepSeek）、
	 * 快讯主要看华尔街见闻的场景，省去代理绕行。历史数据为 null 时按开（true）处理。
	 */
	@Column(name = "use_for_ai", nullable = false)
	private Boolean useForAi = true;

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

	public ProxyType getType() {
		return type;
	}

	public void setType(ProxyType type) {
		this.type = type;
	}

	public String getHost() {
		return host;
	}

	public void setHost(String host) {
		this.host = host;
	}

	public Integer getPort() {
		return port;
	}

	public void setPort(Integer port) {
		this.port = port;
	}

	public String getUsername() {
		return username;
	}

	public void setUsername(String username) {
		this.username = username;
	}

	public String getPassword() {
		return password;
	}

	public void setPassword(String password) {
		this.password = password;
	}

	public Boolean getEnabled() {
		return enabled;
	}

	public void setEnabled(Boolean enabled) {
		this.enabled = enabled;
	}

	public Boolean getUseForAi() {
		return useForAi;
	}

	public void setUseForAi(Boolean useForAi) {
		this.useForAi = useForAi;
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
