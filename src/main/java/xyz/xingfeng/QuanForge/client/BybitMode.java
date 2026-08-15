package xyz.xingfeng.QuanForge.client;

/**
 * Bybit 运行模式：实盘与虚拟盘，区别仅在于请求基础地址。
 * 切换模式即切换 baseUrl，签名逻辑一致。
 */
public enum BybitMode {

	/** 实盘 */
	REAL("https://api.bybit.com"),

	/** 虚拟盘（Demo） */
	DEMO("https://api-demo.bybit.com");

	private final String baseUrl;

	BybitMode(String baseUrl) {
		this.baseUrl = baseUrl;
	}

	public String getBaseUrl() {
		return baseUrl;
	}
}
