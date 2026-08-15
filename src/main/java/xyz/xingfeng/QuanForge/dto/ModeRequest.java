package xyz.xingfeng.QuanForge.dto;

import jakarta.validation.constraints.NotBlank;

/**
 * 切换 Bybit 运行模式的请求体。
 */
public record ModeRequest(@NotBlank(message = "模式不能为空") String mode) {
}
