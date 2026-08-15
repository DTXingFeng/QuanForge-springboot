package xyz.xingfeng.QuanForge.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import xyz.xingfeng.QuanForge.entity.AiAlert;

import java.util.List;

/** AI 告警仓库 */
public interface AiAlertRepository extends JpaRepository<AiAlert, Long> {

	/** 最近告警（时间倒序） */
	List<AiAlert> findTop50ByOrderByCreatedAtDesc();
}
