package xyz.xingfeng.QuanForge.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import xyz.xingfeng.QuanForge.entity.ProxyConfig;

/**
 * 代理配置数据访问层。
 */
public interface ProxyConfigRepository extends JpaRepository<ProxyConfig, Long> {
}
