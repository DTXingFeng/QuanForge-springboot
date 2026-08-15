package xyz.xingfeng.QuanForge.controller;

import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import xyz.xingfeng.QuanForge.dto.ProxyConfigRequest;
import xyz.xingfeng.QuanForge.dto.ProxyConfigResponse;
import xyz.xingfeng.QuanForge.entity.ProxyConfig;
import xyz.xingfeng.QuanForge.service.ProxyConfigService;

/**
 * 代理配置管理接口（全局单例：仅一条记录）。
 */
@RestController
@RequestMapping("/api/proxy")
public class ProxyConfigController {

	private final ProxyConfigService service;

	public ProxyConfigController(ProxyConfigService service) {
		this.service = service;
	}

	/** 获取代理配置（未配置时返回 404） */
	@GetMapping
	public ResponseEntity<ProxyConfigResponse> get() {
		return service.getConfig()
				.map(c -> ResponseEntity.ok(ProxyConfigResponse.from(c)))
				.orElseGet(() -> ResponseEntity.notFound().build());
	}

	/** 保存或更新代理配置（全局唯一，覆盖既有记录） */
	@PutMapping
	public ProxyConfigResponse save(@Valid @RequestBody ProxyConfigRequest req) {
		ProxyConfig config = new ProxyConfig();
		config.setType(req.type());
		config.setHost(req.host());
		config.setPort(req.port());
		config.setUsername(req.username());
		config.setPassword(req.password());
		config.setEnabled(req.enabled() != null ? req.enabled() : Boolean.FALSE);
		config.setUseForAi(req.useForAi());
		return ProxyConfigResponse.from(service.save(config));
	}

	/** 删除代理配置 */
	@DeleteMapping
	@ResponseStatus(HttpStatus.NO_CONTENT)
	public void delete() {
		service.delete();
	}
}
