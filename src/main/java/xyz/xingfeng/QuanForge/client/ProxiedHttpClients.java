package xyz.xingfeng.QuanForge.client;

import okhttp3.Credentials;
import okhttp3.OkHttpClient;
import org.springframework.stereotype.Component;
import xyz.xingfeng.QuanForge.entity.ProxyConfig;
import xyz.xingfeng.QuanForge.entity.ProxyType;
import xyz.xingfeng.QuanForge.service.ProxyConfigService;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.Proxy;
import java.net.URI;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 通用出站 HTTP 客户端工厂：快讯拉取、AI 调用等非 Bybit 场景共用。
 * <p>
 * 与 Bybit 客户端一致地遵循代理配置（每次请求读取最新已启用代理，改代理即时生效）；
 * 按代理签名 + 超时档位缓存客户端，代理未启用则直连。
 */
@Component
public class ProxiedHttpClients {

	/** 常规档位：快讯拉取等（读 20s） */
	public static final long REGULAR = 20_000;

	/** 慢速档位：LLM 推理（读 120s） */
	public static final long SLOW = 120_000;

	private static final String DIRECT_KEY = "direct";

	private final ProxyConfigService proxyConfigService;

	/** 缓存键 = 代理签名:超时档位 */
	private final Map<String, OkHttpClient> clients = new ConcurrentHashMap<>();

	public ProxiedHttpClients(ProxyConfigService proxyConfigService) {
		this.proxyConfigService = proxyConfigService;
	}

	/** 常规超时客户端（连接 10s / 读 20s） */
	public OkHttpClient obtain() {
		return obtain(REGULAR);
	}

	/** 指定读超时（毫秒）的客户端；同一代理与超时档位复用实例 */
	public OkHttpClient obtain(long readTimeoutMillis) {
		Optional<ProxyConfig> proxyOpt = proxyConfigService.getEnabledConfig()
				// 「AI 与快讯走代理」开关关闭时，此通道一律直连（Bybit 客户端不受影响）
				.filter(c -> !Boolean.FALSE.equals(c.getUseForAi()));
		return build(proxyOpt, readTimeoutMillis, "");
	}

	/**
	 * 强制代理档位：忽略「AI 与快讯走代理」开关，只要代理启用就走。
	 * 供被墙服务使用（如 Telegram API）——直连必失败，跟随 Bybit 的代理策略。
	 */
	public OkHttpClient obtainAlwaysProxied(long readTimeoutMillis) {
		Optional<ProxyConfig> proxyOpt = proxyConfigService.getEnabledConfig();
		return build(proxyOpt, readTimeoutMillis, "force:");
	}

	private OkHttpClient build(Optional<ProxyConfig> proxyOpt, long readTimeoutMillis,
			String keyPrefix) {
		String suffix = keyPrefix + ":" + readTimeoutMillis;
		if (proxyOpt.isEmpty()) {
			return clients.computeIfAbsent(DIRECT_KEY + suffix,
					k -> baseBuilder(readTimeoutMillis).build());
		}
		ProxyConfig config = proxyOpt.get();
		String key = signature(config) + suffix;
		return clients.computeIfAbsent(key, k -> {
			OkHttpClient.Builder builder = baseBuilder(readTimeoutMillis);
			applyProxy(builder, config);
			return builder.build();
		});
	}

	private OkHttpClient.Builder baseBuilder(long readTimeoutMillis) {
		return new OkHttpClient.Builder()
				.connectTimeout(Duration.ofSeconds(10))
				.readTimeout(Duration.ofMillis(readTimeoutMillis))
				.writeTimeout(Duration.ofSeconds(15));
	}

	/** 代理签名键：类型:主机:端口:用户名（密码不参与） */
	private String signature(ProxyConfig config) {
		String type = config.getType() == ProxyType.SOCKS ? "SOCKS" : "HTTP";
		String username = config.getUsername() == null ? "" : config.getUsername();
		return type + ":" + config.getHost() + ":" + config.getPort() + ":" + username;
	}

	/** 判断目标是否本机（本机服务不走代理，避免代理回环 502） */
	private static boolean isLocal(String host) {
		return host == null
				|| host.equalsIgnoreCase("localhost")
				|| host.equals("127.0.0.1")
				|| host.equals("::1")
				|| host.equals("0.0.0.0");
	}

	private void applyProxy(OkHttpClient.Builder builder, ProxyConfig config) {
		Proxy.Type type = config.getType() == ProxyType.SOCKS ? Proxy.Type.SOCKS : Proxy.Type.HTTP;
		Proxy proxy = new Proxy(type, new InetSocketAddress(config.getHost(), config.getPort()));

		// 本机目标（本地 Ollama / mock 等）直连，其余走代理
		builder.proxySelector(new java.net.ProxySelector() {
			@Override
			public List<Proxy> select(URI uri) {
				if (isLocal(uri.getHost())) {
					return List.of(Proxy.NO_PROXY);
				}
				return List.of(proxy);
			}

			@Override
			public void connectFailed(URI uri, java.net.SocketAddress sa, IOException e) {
				// 连接失败交给 OkHttp 重试机制
			}
		});

		String username = config.getUsername();
		String password = config.getPassword();
		if (username != null && !username.isBlank()) {
			builder.proxyAuthenticator((route, response) -> response.request().newBuilder()
					.header("Proxy-Authorization",
							Credentials.basic(username, password == null ? "" : password))
					.build());
		}
	}
}
