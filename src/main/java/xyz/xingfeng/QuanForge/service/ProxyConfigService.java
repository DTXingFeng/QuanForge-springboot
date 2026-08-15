package xyz.xingfeng.QuanForge.service;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import xyz.xingfeng.QuanForge.entity.ProxyConfig;
import xyz.xingfeng.QuanForge.repository.ProxyConfigRepository;

import java.util.Optional;

/**
 * 代理配置服务：保证全局仅一条代理记录（固定主键 SINGLETON_ID）。
 * 提供 OkHttp 所需代理参数的读取与保存。
 */
@Service
public class ProxyConfigService {

	private final ProxyConfigRepository repository;

	public ProxyConfigService(ProxyConfigRepository repository) {
		this.repository = repository;
	}

	/** 获取当前代理配置（可能为空，表示尚未配置） */
	@Transactional(readOnly = true)
	public Optional<ProxyConfig> getConfig() {
		return repository.findById(ProxyConfig.SINGLETON_ID);
	}

	/** 获取已启用的代理配置（供 OkHttp 客户端使用；未配置或未启用时返回空） */
	@Transactional(readOnly = true)
	public Optional<ProxyConfig> getEnabledConfig() {
		return getConfig().filter(c -> Boolean.TRUE.equals(c.getEnabled()));
	}

	/** 保存或更新代理配置（全局唯一，固定主键，覆盖既有记录） */
	@Transactional
	public ProxyConfig save(ProxyConfig config) {
		return repository.findById(ProxyConfig.SINGLETON_ID)
				.map(existing -> {
					existing.setType(config.getType());
					existing.setHost(config.getHost());
					existing.setPort(config.getPort());
					existing.setUsername(config.getUsername());
					existing.setPassword(config.getPassword());
					existing.setEnabled(config.getEnabled());
					existing.setUseForAi(config.getUseForAi() == null ? Boolean.TRUE : config.getUseForAi());
					return repository.save(existing);
				})
				.orElseGet(() -> {
					config.setId(ProxyConfig.SINGLETON_ID);
					if (config.getUseForAi() == null) {
						config.setUseForAi(Boolean.TRUE);
					}
					return repository.save(config);
				});
	}

	/** 删除代理配置 */
	@Transactional
	public void delete() {
		repository.findById(ProxyConfig.SINGLETON_ID).ifPresent(repository::delete);
	}
}
