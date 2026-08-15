package xyz.xingfeng.QuanForge.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import xyz.xingfeng.QuanForge.entity.ApiCredential;

import java.util.Optional;

/**
 * API 凭证数据访问层。
 */
public interface ApiCredentialRepository extends JpaRepository<ApiCredential, Long> {

	/** 按凭证标识查询 */
	Optional<ApiCredential> findByName(String name);

	/** 判断指定标识是否已存在 */
	boolean existsByName(String name);
}
