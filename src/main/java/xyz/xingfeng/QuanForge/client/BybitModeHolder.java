package xyz.xingfeng.QuanForge.client;

import org.springframework.stereotype.Component;

/**
 * Bybit 运行模式的全局持有者。
 * <p>
 * GET 与 POST 客户端共享同一份模式：切换一次，两个客户端同步生效（基础地址一致）。
 * 默认主打虚拟盘（DEMO）。
 */
@Component
public class BybitModeHolder {

	/** 当前运行模式（volatile 保证多线程可见性） */
	private volatile BybitMode mode = BybitMode.DEMO;

	/** 获取当前运行模式 */
	public BybitMode getMode() {
		return mode;
	}

	/** 切换运行模式（实盘/虚拟盘）；传入 null 时忽略 */
	public void setMode(BybitMode mode) {
		if (mode != null) {
			this.mode = mode;
		}
	}
}
