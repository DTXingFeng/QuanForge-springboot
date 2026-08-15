package xyz.xingfeng.QuanForge.service;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import xyz.xingfeng.QuanForge.entity.ApiCredential;
import xyz.xingfeng.QuanForge.repository.ApiCredentialRepository;

import java.util.List;
import java.util.Optional;

/**
 * API 凭证服务：封装凭证的增删改查。
 */
@Service
public class ApiCredentialService {

	private final ApiCredentialRepository repository;

	public ApiCredentialService(ApiCredentialRepository repository) {
		this.repository = repository;
	}

	/** 保存或更新凭证 */
	@Transactional
	public ApiCredential save(ApiCredential credential) {
		return repository.save(credential);
	}

	/** 按主键查询 */
	@Transactional(readOnly = true)
	public Optional<ApiCredential> findById(Long id) {
		return repository.findById(id);
	}

	/** 按凭证标识查询 */
	@Transactional(readOnly = true)
	public Optional<ApiCredential> findByName(String name) {
		return repository.findByName(name);
	}

	/** 查询全部凭证 */
	@Transactional(readOnly = true)
	public List<ApiCredential> findAll() {
		return repository.findAll();
	}

	/** 判断指定标识是否已存在 */
	@Transactional(readOnly = true)
	public boolean existsByName(String name) {
		return repository.existsByName(name);
	}

	/** 按主键删除 */
	@Transactional
	public void deleteById(Long id) {
		repository.deleteById(id);
	}
}
