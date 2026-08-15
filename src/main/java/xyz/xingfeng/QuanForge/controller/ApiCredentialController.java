package xyz.xingfeng.QuanForge.controller;

import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import xyz.xingfeng.QuanForge.dto.ApiCredentialDetailResponse;
import xyz.xingfeng.QuanForge.dto.ApiCredentialRequest;
import xyz.xingfeng.QuanForge.dto.ApiCredentialResponse;
import xyz.xingfeng.QuanForge.entity.ApiCredential;
import xyz.xingfeng.QuanForge.exception.NotFoundException;
import xyz.xingfeng.QuanForge.service.ApiCredentialService;

import java.util.List;

/**
 * API 凭证管理接口。
 */
@RestController
@RequestMapping("/api/credentials")
public class ApiCredentialController {

	private final ApiCredentialService service;

	public ApiCredentialController(ApiCredentialService service) {
		this.service = service;
	}

	/** 创建凭证 */
	@PostMapping
	@ResponseStatus(HttpStatus.CREATED)
	public ApiCredentialDetailResponse create(@Valid @RequestBody ApiCredentialRequest req) {
		ApiCredential credential = new ApiCredential();
		credential.setName(req.name());
		credential.setApiKey(req.apiKey());
		credential.setApiSecret(req.apiSecret());
		return ApiCredentialDetailResponse.from(service.save(credential));
	}

	/** 凭证列表（脱敏，不含 secret） */
	@GetMapping
	public List<ApiCredentialResponse> list() {
		return service.findAll().stream().map(ApiCredentialResponse::from).toList();
	}

	/** 凭证详情（明文） */
	@GetMapping("/{id}")
	public ApiCredentialDetailResponse get(@PathVariable Long id) {
		return service.findById(id)
				.map(ApiCredentialDetailResponse::from)
				.orElseThrow(() -> new NotFoundException("凭证不存在: " + id));
	}

	/** 更新凭证 */
	@PutMapping("/{id}")
	public ApiCredentialDetailResponse update(@PathVariable Long id, @Valid @RequestBody ApiCredentialRequest req) {
		ApiCredential credential = service.findById(id)
				.orElseThrow(() -> new NotFoundException("凭证不存在: " + id));
		credential.setName(req.name());
		credential.setApiKey(req.apiKey());
		credential.setApiSecret(req.apiSecret());
		return ApiCredentialDetailResponse.from(service.save(credential));
	}

	/** 删除凭证 */
	@DeleteMapping("/{id}")
	@ResponseStatus(HttpStatus.NO_CONTENT)
	public void delete(@PathVariable Long id) {
		service.deleteById(id);
	}
}
