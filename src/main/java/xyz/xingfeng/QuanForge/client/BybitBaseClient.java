package xyz.xingfeng.QuanForge.client;

import okhttp3.Credentials;
import okhttp3.OkHttpClient;
import xyz.xingfeng.QuanForge.entity.ProxyConfig;
import xyz.xingfeng.QuanForge.entity.ProxyType;
import xyz.xingfeng.QuanForge.service.ProxyConfigService;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.net.InetSocketAddress;
import java.net.Proxy;
import java.nio.charset.StandardCharsets;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * GET/POST 客户端公共基类：统一管理运行模式、动态代理缓存与 HMAC-SHA256 签名。
 * <p>
 * 运行模式（实盘/虚拟盘）由 {@link BybitModeHolder} 全局持有，GET 与 POST 共享；
 * 代理为运行时动态读取，每次请求按最新已启用代理配置选取客户端，改代理即时生效，无需重启。
 */
public abstract class BybitBaseClient {

	/** 接收窗口（毫秒），Bybit 默认 5000 */
	protected static final String RECV_WINDOW = "5000";

	/** 直连（无代理）客户端的缓存键 */
	private static final String DIRECT_KEY = "direct";

	protected final ProxyConfigService proxyConfigService;
	protected final BybitModeHolder modeHolder;

	/** 按代理签名缓存 OkHttpClient，代理变更产生新 key 即构建新客户端 */
	private final ConcurrentHashMap<String, OkHttpClient> clients = new ConcurrentHashMap<>();

	protected BybitBaseClient(ProxyConfigService proxyConfigService, BybitModeHolder modeHolder) {
		this.proxyConfigService = proxyConfigService;
		this.modeHolder = modeHolder;
	}

	/** 获取当前运行模式（实盘/虚拟盘） */
	public BybitMode getMode() {
		return modeHolder.getMode();
	}

	/** 切换运行模式，切换后基础地址立即在 GET/POST 两端同步生效 */
	public void setMode(BybitMode mode) {
		modeHolder.setMode(mode);
	}

	/** 当前请求基础地址 */
	protected String baseUrl() {
		return modeHolder.getMode().getBaseUrl();
	}

	/**
	 * 按当前已启用的代理配置获取客户端：无代理则直连；有代理则按代理签名复用或新建。
	 * 代理配置变更后签名不同，自动构建新客户端，旧客户端保留在缓存中（规模可控）。
	 */
	protected OkHttpClient obtainClient() {
		Optional<ProxyConfig> proxyOpt = proxyConfigService.getEnabledConfig();
		if (proxyOpt.isEmpty()) {
			return clients.computeIfAbsent(DIRECT_KEY, k -> baseBuilder().build());
		}
		ProxyConfig config = proxyOpt.get();
		String key = proxyKey(config);
		return clients.computeIfAbsent(key, k -> {
			OkHttpClient.Builder builder = baseBuilder();
			applyProxy(builder, config);
			return builder.build();
		});
	}

	/**
	 * 基础构建器：显式全套超时。OkHttp 默认 readTimeout(10s) 是 socket 级的，
	 * HTTP/2 连接上有帧流动就不断重置——stream 层等响应头可无限挂死
	 * （ProxiedHttpClients 同款问题，见其注释）。callTimeout 到点强制取消整个调用。
	 */
	private OkHttpClient.Builder baseBuilder() {
		return new OkHttpClient.Builder()
				.connectTimeout(java.time.Duration.ofSeconds(10))
				.readTimeout(java.time.Duration.ofSeconds(20))
				.writeTimeout(java.time.Duration.ofSeconds(15))
				.callTimeout(java.time.Duration.ofSeconds(30));
	}

	/** 生成代理签名键：类型:主机:端口:用户名（密码不参与，避免明文留痕） */
	private String proxyKey(ProxyConfig config) {
		String type = config.getType() == ProxyType.SOCKS ? "SOCKS" : "HTTP";
		String username = config.getUsername() == null ? "" : config.getUsername();
		return type + ":" + config.getHost() + ":" + config.getPort() + ":" + username;
	}

	/** HMAC-SHA256 计算并转为十六进制小写 */
	protected String hmacSha256Hex(String secret, String data) throws Exception {
		Mac mac = Mac.getInstance("HmacSHA256");
		mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
		byte[] raw = mac.doFinal(data.getBytes(StandardCharsets.UTF_8));
		StringBuilder sb = new StringBuilder(raw.length * 2);
		for (byte b : raw) {
			sb.append(Character.forDigit((b >> 4) & 0xF, 16));
			sb.append(Character.forDigit(b & 0xF, 16));
		}
		return sb.toString();
	}

	/** 将代理配置应用到 OkHttp 客户端构建器 */
	private void applyProxy(OkHttpClient.Builder builder, ProxyConfig config) {
		Proxy.Type type = config.getType() == ProxyType.SOCKS ? Proxy.Type.SOCKS : Proxy.Type.HTTP;
		builder.proxy(new Proxy(type, new InetSocketAddress(config.getHost(), config.getPort())));

		String username = config.getUsername();
		String password = config.getPassword();
		if (username != null && !username.isBlank()) {
			// 代理需要鉴权时，补上 Proxy-Authorization 头
			builder.proxyAuthenticator((route, response) -> response.request().newBuilder()
					.header("Proxy-Authorization", Credentials.basic(username, password == null ? "" : password))
					.build());
		}
	}
}
