package xyz.xingfeng.QuanForge.controller;

import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import xyz.xingfeng.QuanForge.entity.TelegramConfig;
import xyz.xingfeng.QuanForge.service.TelegramBotService;

import java.util.Map;

/**
 * Telegram 机器人配置接口：token/chatId 读写（token 打码）、启用开关、连通性测试。
 */
@RestController
@RequestMapping("/api/tg")
public class TelegramController {

	private final TelegramBotService botService;

	public TelegramController(TelegramBotService botService) {
		this.botService = botService;
	}

	public record TgConfigRequest(String botToken, String chatId, Boolean enabled) {
	}

	public record TgConfigResponse(boolean tokenSet, String maskedToken, String chatId,
			boolean enabled, boolean bound) {
	}

	@GetMapping("/config")
	public TgConfigResponse getConfig() {
		TelegramConfig c = botService.getConfig();
		boolean tokenSet = c.getBotToken() != null && !c.getBotToken().isBlank();
		return new TgConfigResponse(tokenSet, mask(c.getBotToken()), c.getChatId(),
				Boolean.TRUE.equals(c.getEnabled()), !c.getChatId().isBlank());
	}

	/** 保存（botToken 留空表示不修改；chatId 传空串表示解绑） */
	@PutMapping("/config")
	public TgConfigResponse save(@Valid @RequestBody TgConfigRequest req) {
		TelegramConfig saved = botService.save(req.botToken(), req.chatId(), req.enabled());
		boolean tokenSet = !saved.getBotToken().isBlank();
		return new TgConfigResponse(tokenSet, mask(saved.getBotToken()), saved.getChatId(),
				Boolean.TRUE.equals(saved.getEnabled()), !saved.getChatId().isBlank());
	}

	/** 发送测试消息（需已绑定 chatId） */
	@PostMapping("/test")
	public ResponseEntity<?> test() {
		TelegramConfig c = botService.getConfig();
		if (c.getBotToken().isBlank() || c.getChatId().isBlank()) {
			return ResponseEntity.badRequest().body(Map.of("ok", false,
					"message", "请先填写 token 并给机器人发 /start 完成绑定"));
		}
		botService.send("✅ QuanForge 测试消息：通道正常。回复 /help 查看指令。");
		return ResponseEntity.ok(Map.of("ok", true));
	}

	private String mask(String token) {
		if (token == null || token.length() < 8) {
			return token == null || token.isEmpty() ? "" : "****";
		}
		return token.substring(0, 6) + "****" + token.substring(token.length() - 4);
	}
}
