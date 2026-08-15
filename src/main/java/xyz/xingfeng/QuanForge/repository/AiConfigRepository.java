package xyz.xingfeng.QuanForge.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import xyz.xingfeng.QuanForge.entity.AiConfig;

/** AI 配置仓库（全局单例） */
public interface AiConfigRepository extends JpaRepository<AiConfig, Long> {
}
