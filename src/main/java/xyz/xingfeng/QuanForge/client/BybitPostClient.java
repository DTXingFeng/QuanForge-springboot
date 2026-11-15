package xyz.xingfeng.QuanForge.client;

import okhttp3.MediaType;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import org.springframework.stereotype.Component;
import xyz.xingfeng.QuanForge.service.ProxyConfigService;

import java.time.Instant;

/**
 * Bybit V5 POST 请求客户端（基于 OkHttp）。
 * <p>
 * POST 与 GET 采用不同的签名串构造方式：POST 直接使用请求体原文参与签名，
 * {@code sign = HMAC-SHA256(secret, timestamp + apiKey + recvWindow + rawRequestBody)}，
 * 不对参数排序也不做 URL 编码；请求体按 Bybit 要求以 application/json 原样发送。
 * <p>
 * 签名明文示例：
 * <pre>
 * 1658385579423XXXXXXXXXX5000{"category":"option"}
 * ├─timestamp─┘├─apiKey─┘├recv┘├── rawRequestBody ──┘
 * </pre>
 * <p>
 * 运行模式与代理配置与 GET 客户端共享（经 {@link BybitModeHolder} 与同一 ProxyConfigService）。
 */
@Component
public class BybitPostClient extends BybitBaseClient {
	@org.springframework.beans.factory.annotation.Autowired
	private xyz.xingfeng.QuanForge.service.CredentialHealthRegistry credentialHealth;
	/** All signed account mutations require a separate, explicit deployment switch. */
	@org.springframework.beans.factory.annotation.Value("${app.execution.account-writes-enabled:false}")
	private boolean accountWritesEnabled = false;

	/** JSON 请求体媒体类型 */
	private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");

	public BybitPostClient(ProxyConfigService proxyConfigService, BybitModeHolder modeHolder) {
		super(proxyConfigService, modeHolder);
	}

	/**
	 * 发起签名 POST 请求（使用当前运行模式基础地址与最新代理配置）。
	 *
	 * @param apiKey         API Key（明文）
	 * @param apiSecret      API Secret（明文）
	 * @param endpoint       接口路径，如 /v5/order/create
	 * @param rawRequestBody 原始请求体（JSON 字符串），将原样参与签名并以 application/json 发送
	 * @return 响应体字符串
	 */
	public String post(String apiKey, String apiSecret, String endpoint, String rawRequestBody)
			throws Exception {
		return postTo(baseUrl(), apiKey, apiSecret, endpoint, rawRequestBody);
	}

	/** Automatic demo execution is pinned to the demo host, independent of UI mode changes. */
	public String postDemo(String apiKey, String apiSecret, String endpoint, String rawRequestBody)
			throws Exception {
		return postTo(BybitMode.DEMO.getBaseUrl(), apiKey, apiSecret, endpoint, rawRequestBody);
	}

	private String postTo(String requestBase, String apiKey, String apiSecret,
			String endpoint, String rawRequestBody) throws Exception {
		if (!accountWritesEnabled) {
			throw new IllegalStateException("账户写操作未启用：候选版本默认仅允许只读验证");
		}
		// 空请求体按空串处理，签名仍需包含该段（Bybit 约定）
		String body = rawRequestBody == null ? "" : rawRequestBody;

		// 1. 时间戳（UTC 毫秒）
		String timestamp = String.valueOf(Instant.now().toEpochMilli());

		// 2. 签名串 = timestamp + apiKey + recvWindow + rawRequestBody（明文，不编码）
		String signSource = timestamp + apiKey + RECV_WINDOW + body;

		// 3. HMAC-SHA256 转十六进制小写
		String sign = hmacSha256Hex(apiSecret, signSource);

		// 4. 拼接完整 URL
		String url = requestBase + endpoint;

		// 5. 构建带签名请求头的 POST（请求体原样发送）
		Request request = new Request.Builder()
				.url(url)
				.post(RequestBody.create(body, JSON))
				.header("X-BAPI-API-KEY", apiKey)
				.header("X-BAPI-SIGN", sign)
				.header("X-BAPI-TIMESTAMP", timestamp)
				.header("X-BAPI-RECV-WINDOW", RECV_WINDOW)
				.header("X-BAPI-SIGN-TYPE", "2")
				.header("Content-Type", "application/json")
				.build();

		try (Response response = obtainClient().newCall(request).execute()) {
			String raw=response.body() != null ? response.body().string() : "";
			if(credentialHealth!=null)credentialHealth.observe(apiKey,apiSecret,
					requestBase.equals(BybitMode.DEMO.getBaseUrl())?BybitMode.DEMO:BybitMode.REAL,response.code(),raw);
			return raw;
		} catch(java.io.IOException e) {
			if(credentialHealth!=null)credentialHealth.networkFailure(apiKey,apiSecret,
					requestBase.equals(BybitMode.DEMO.getBaseUrl())?BybitMode.DEMO:BybitMode.REAL);
			throw e;
		}
	}
}
