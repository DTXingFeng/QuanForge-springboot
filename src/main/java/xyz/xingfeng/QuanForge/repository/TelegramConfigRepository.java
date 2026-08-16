package xyz.xingfeng.QuanForge.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import xyz.xingfeng.QuanForge.entity.TelegramConfig;

public interface TelegramConfigRepository extends JpaRepository<TelegramConfig, Long> {
}
