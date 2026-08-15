package xyz.xingfeng.QuanForge;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * HTTP 接口集成测试：以真实端口启动服务，用 JDK HttpClient 验证凭证与代理配置的完整流程。
 * JSON 用 org.json 构造与解析（controller 运行时序列化由 Spring Boot 4 自带的 Jackson 3 处理）。
 * 数据隔离：凭证使用唯一 name，代理单例在用例开头先删除。
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class ApiControllerTests {

	@LocalServerPort
	int port;

	private final HttpClient client = HttpClient.newHttpClient();

	/** 发送请求并返回响应。body 非 null 时作为 JSON 请求体发送。 */
	private HttpResponse<String> http(String method, String path, JSONObject body) throws Exception {
		HttpRequest.Builder builder = HttpRequest.newBuilder().uri(URI.create("http://localhost:" + port + path));
		switch (method) {
			case "GET" -> builder.GET();
			case "DELETE" -> builder.DELETE();
			case "POST" -> builder.header("Content-Type", "application/json")
					.POST(HttpRequest.BodyPublishers.ofString(body.toString()));
			case "PUT" -> builder.header("Content-Type", "application/json")
					.PUT(HttpRequest.BodyPublishers.ofString(body.toString()));
			default -> throw new IllegalArgumentException("不支持的 method: " + method);
		}
		return client.send(builder.build(), HttpResponse.BodyHandlers.ofString());
	}

	/** 凭证完整增删改查：创建→详情→列表脱敏→更新→删除→404 */
	@Test
	void credentialFullCycle() throws Exception {
		String name = "openai-" + UUID.randomUUID();
		JSONObject req = new JSONObject()
				.put("name", name)
				.put("apiKey", "sk-abcdef123456")
				.put("apiSecret", "secret-xyz");

		// 创建
		HttpResponse<String> cr = http("POST", "/api/credentials", req);
		assertThat(cr.statusCode()).isEqualTo(201);
		JSONObject created = new JSONObject(cr.body());
		assertThat(created.getString("name")).isEqualTo(name);
		assertThat(created.getString("apiKey")).isEqualTo("sk-abcdef123456");
		assertThat(created.getString("apiSecret")).isEqualTo("secret-xyz");
		int id = created.getInt("id");

		// 详情返回明文
		HttpResponse<String> dr = http("GET", "/api/credentials/" + id, null);
		assertThat(dr.statusCode()).isEqualTo(200);
		assertThat(new JSONObject(dr.body()).getString("apiKey")).isEqualTo("sk-abcdef123456");

		// 列表脱敏：定位到本次创建的记录
		HttpResponse<String> lr = http("GET", "/api/credentials", null);
		assertThat(lr.statusCode()).isEqualTo(200);
		JSONArray arr = new JSONArray(lr.body());
		JSONObject mine = null;
		for (int i = 0; i < arr.length(); i++) {
			JSONObject n = arr.getJSONObject(i);
			if (n.getInt("id") == id) {
				mine = n;
				break;
			}
		}
		assertThat(mine).isNotNull();
		assertThat(mine.getString("maskedApiKey")).isEqualTo("sk-a********3456");
		assertThat(mine.has("apiKey")).isFalse();

		// 更新
		JSONObject upd = new JSONObject()
				.put("name", name)
				.put("apiKey", "sk-newkey999888")
				.put("apiSecret", "secret-new");
		HttpResponse<String> ur = http("PUT", "/api/credentials/" + id, upd);
		assertThat(ur.statusCode()).isEqualTo(200);
		assertThat(new JSONObject(ur.body()).getString("apiKey")).isEqualTo("sk-newkey999888");

		// 删除
		assertThat(http("DELETE", "/api/credentials/" + id, null).statusCode()).isEqualTo(204);

		// 删除后 404
		assertThat(http("GET", "/api/credentials/" + id, null).statusCode()).isEqualTo(404);
	}

	/** 凭证名重复 → 409 */
	@Test
	void credentialDuplicateNameReturns409() throws Exception {
		String name = "dup-" + UUID.randomUUID();
		JSONObject req = new JSONObject().put("name", name).put("apiKey", "k1").put("apiSecret", "s1");

		HttpResponse<String> first = http("POST", "/api/credentials", req);
		assertThat(first.statusCode()).isEqualTo(201);
		int id = new JSONObject(first.body()).getInt("id");

		HttpResponse<String> second = http("POST", "/api/credentials", req);
		assertThat(second.statusCode()).isEqualTo(409);

		// 清理
		http("DELETE", "/api/credentials/" + id, null);
	}

	/** 请求体校验失败 → 400 */
	@Test
	void credentialInvalidBodyReturns400() throws Exception {
		JSONObject req = new JSONObject().put("name", "").put("apiKey", "").put("apiSecret", "");
		HttpResponse<String> resp = http("POST", "/api/credentials", req);
		assertThat(resp.statusCode()).isEqualTo(400);
	}

	/** 代理配置生命周期：未配置 404→保存→读取→删除→404 */
	@Test
	void proxyLifecycle() throws Exception {
		// 先清空可能存在的单例配置
		http("DELETE", "/api/proxy", null);

		// 未配置时 404
		assertThat(http("GET", "/api/proxy", null).statusCode()).isEqualTo(404);

		// 保存（密码明文出入，落库已加密）
		JSONObject req = new JSONObject()
				.put("type", "HTTP")
				.put("host", "127.0.0.1")
				.put("port", 8080)
				.put("username", "u")
				.put("password", "p")
				.put("enabled", true);
		HttpResponse<String> sr = http("PUT", "/api/proxy", req);
		assertThat(sr.statusCode()).isEqualTo(200);
		JSONObject saved = new JSONObject(sr.body());
		assertThat(saved.getString("host")).isEqualTo("127.0.0.1");
		assertThat(saved.getBoolean("enabled")).isTrue();
		assertThat(saved.getString("password")).isEqualTo("p");

		// 读取
		HttpResponse<String> gr = http("GET", "/api/proxy", null);
		assertThat(gr.statusCode()).isEqualTo(200);
		assertThat(new JSONObject(gr.body()).getString("host")).isEqualTo("127.0.0.1");

		// 删除
		assertThat(http("DELETE", "/api/proxy", null).statusCode()).isEqualTo(204);

		// 删除后 404
		assertThat(http("GET", "/api/proxy", null).statusCode()).isEqualTo(404);
	}
}
