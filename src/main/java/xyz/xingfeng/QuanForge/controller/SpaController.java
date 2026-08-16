package xyz.xingfeng.QuanForge.controller;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

/**
 * SPA 路由转发：前端使用 BrowserRouter，刷新/直连子路径时由后端转发到 index.html，
 * 交由前端路由接管。API（/api/**）与静态资源由 Spring 默认机制处理，不受影响。
 */
@Controller
public class SpaController {

	@GetMapping({"/", "/trade", "/news-ai", "/credentials", "/history", "/settings"})
	public String spa() {
		return "forward:/index.html";
	}
}
