package xyz.xingfeng.QuanForge.client;

import okhttp3.Request;
import okhttp3.Response;
import org.springframework.stereotype.Component;
import xyz.xingfeng.QuanForge.service.ProxyConfigService;

import java.time.Instant;
import java.util.Collections;
import java.util.Map;
import java.util.TreeMap;

/**
 * Bybit V5 GET 请求客户端（基于 OkHttp）。
 * <p>
 * 将请求参数按 key 字典序升序拼接为 {@code key=value&...} 作为签名原文，
 * 再 {@code sign = HMAC-SHA256(secret, timestamp + apiKey + recvWindow + 原文)} 转十六进制。
 * <p>
 * 运行模式与代理配置经公共基类 {@link BybitBaseClient} 管理，与 POST 客户端共享。
 */
@Component
public class BybitGetClient extends BybitBaseClient {

	public BybitGetClient(ProxyConfigService proxyConfigService, BybitModeHolder modeHolder) {
		super(proxyConfigService, modeHolder);
	}

	/**
	 * 发起一个签名 GET 请求（使用当前运行模式的基础地址与最新代理配置）。
	 *
	 * @param apiKey    API Key（明文）
	 * @param apiSecret API Secret（明文）
	 * @param endpoint  接口路径，如 /v5/account/wallet-balance
	 * @param params    查询参数（可为 null），会按 key 字典序排序后参与签名与 URL 拼接
	 * @return 响应体字符串
	 */
	public String get(String apiKey, String apiSecret, String endpoint, Map<String, String> params)
			throws Exception {
		// 1. 参数按 key 字典序排序后拼接为签名原文
		TreeMap<String, String> sorted = new TreeMap<>(params == null ? Collections.emptyMap() : params);
		String paramStr = joinSorted(sorted);

		// 2. 时间戳（UTC 毫秒）
		String timestamp = String.valueOf(Instant.now().toEpochMilli());

		// 3. 签名串 = timestamp + apiKey + recvWindow + paramStr
		String signSource = timestamp + apiKey + RECV_WINDOW + paramStr;

		// 4. HMAC-SHA256 转十六进制小写
		String sign = hmacSha256Hex(apiSecret, signSource);

		// 5. 拼接完整 URL（签名与 URL 均使用未编码原文，符合 Bybit 要求）
		String url = baseUrl() + endpoint + (paramStr.isEmpty() ? "" : "?" + paramStr);

		// 6. 构建带签名的请求头并执行
		Request request = new Request.Builder()
				.url(url)
				.get()
				.header("X-BAPI-API-KEY", apiKey)
				.header("X-BAPI-SIGN", sign)
				.header("X-BAPI-TIMESTAMP", timestamp)
				.header("X-BAPI-RECV-WINDOW", RECV_WINDOW)
				.header("X-BAPI-SIGN-TYPE", "2")
				.build();

		try (Response response = obtainClient().newCall(request).execute()) {
			return response.body() != null ? response.body().string() : "";
		}
	}

	/**
	 * 发起一个<strong>无需签名</strong>的公开 GET 请求（用于行情类接口，如 tickers/kline/instruments-info）。
	 * 不携带任何鉴权头，参数按 key 字典序拼接进 URL。
	 *
	 * @param endpoint 接口路径，如 /v5/market/tickers
	 * @param params   查询参数（可为 null）
	 * @return 响应体字符串
	 */
	public String getPublic(String endpoint, Map<String, String> params) throws Exception {
		TreeMap<String, String> sorted = new TreeMap<>(params == null ? Collections.emptyMap() : params);
		String paramStr = joinSorted(sorted);
		String url = baseUrl() + endpoint + (paramStr.isEmpty() ? "" : "?" + paramStr);

		Request request = new Request.Builder()
				.url(url)
				.get()
				.build();

		try (Response response = obtainClient().newCall(request).execute()) {
			return response.body() != null ? response.body().string() : "";
		}
	}

	/** 将排序后的参数拼接为 key=value&key=value（不进行 URL 编码，符合 Bybit 签名要求） */
	private String joinSorted(TreeMap<String, String> sorted) {
		if (sorted.isEmpty()) {
			return "";
		}
		StringBuilder sb = new StringBuilder();
		sorted.forEach((k, v) -> {
			if (!sb.isEmpty()) {
				sb.append('&');
			}
			sb.append(k).append('=').append(v);
		});
		return sb.toString();
	}
}
