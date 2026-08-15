package xyz.xingfeng.QuanForge;

import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Transactional;
import xyz.xingfeng.QuanForge.crypto.AesEncryptor;
import xyz.xingfeng.QuanForge.entity.ApiCredential;
import xyz.xingfeng.QuanForge.entity.ProxyConfig;
import xyz.xingfeng.QuanForge.entity.ProxyType;
import xyz.xingfeng.QuanForge.service.ApiCredentialService;
import xyz.xingfeng.QuanForge.service.ProxyConfigService;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
class QuanForgeSpringbootApplicationTests {

	@Autowired
	private ApiCredentialService apiCredentialService;

	@Autowired
	private ProxyConfigService proxyConfigService;

	@Autowired
	private AesEncryptor aesEncryptor;

	@Autowired
	private JdbcTemplate jdbcTemplate;

	@PersistenceContext
	private EntityManager entityManager;

	@Test
	void contextLoads() {
	}

	/** 验证凭证可被存入并按标识查出，时间戳自动填充 */
	@Test
	@Transactional
	void saveAndFindApiCredential() {
		ApiCredential credential = new ApiCredential();
		credential.setName("openai");
		credential.setApiKey("sk-test-key");
		credential.setApiSecret("test-secret");

		ApiCredential saved = apiCredentialService.save(credential);

		assertThat(saved.getId()).isNotNull();
		assertThat(saved.getCreatedAt()).isNotNull();
		assertThat(saved.getUpdatedAt()).isNotNull();

		assertThat(apiCredentialService.findByName("openai"))
				.isPresent()
				.get()
				.satisfies(c -> {
					assertThat(c.getApiKey()).isEqualTo("sk-test-key");
					assertThat(c.getApiSecret()).isEqualTo("test-secret");
				});
	}

	/** 验证：落库为密文（非明文），读取时可逆还原为明文 */
	@Test
	@Transactional
	void secretIsEncryptedAtRestAndReversible() {
		ApiCredential credential = new ApiCredential();
		credential.setName("anthropic");
		credential.setApiKey("ak-plain-key");
		credential.setApiSecret("super-secret-value");
		ApiCredential saved = apiCredentialService.save(credential);
		entityManager.flush();
		entityManager.clear();

		// 数据库中实际存储的应为密文
		String dbApiKey = jdbcTemplate.queryForObject(
				"select api_key from api_credential where id = ?", String.class, saved.getId());
		String dbSecret = jdbcTemplate.queryForObject(
				"select api_secret from api_credential where id = ?", String.class, saved.getId());

		assertThat(dbApiKey).isNotEqualTo("ak-plain-key");
		assertThat(dbSecret).isNotEqualTo("super-secret-value");

		// 密文可被加密器还原为明文（可逆）
		assertThat(aesEncryptor.decrypt(dbApiKey)).isEqualTo("ak-plain-key");
		assertThat(aesEncryptor.decrypt(dbSecret)).isEqualTo("super-secret-value");

		// 通过实体读回应为明文（转换器已解密）
		ApiCredential loaded = apiCredentialService.findById(saved.getId()).orElseThrow();
		assertThat(loaded.getApiKey()).isEqualTo("ak-plain-key");
		assertThat(loaded.getApiSecret()).isEqualTo("super-secret-value");
	}

	/** 验证代理配置全局唯一：多次保存始终覆盖同一条（主键固定为 SINGLETON_ID） */
	@Test
	@Transactional
	void proxyConfigIsSingleton() {
		ProxyConfig first = new ProxyConfig();
		first.setType(ProxyType.HTTP);
		first.setHost("127.0.0.1");
		first.setPort(8080);
		first.setEnabled(false);
		proxyConfigService.save(first);

		assertThat(proxyConfigService.getConfig())
				.isPresent()
				.get()
				.satisfies(c -> {
					assertThat(c.getId()).isEqualTo(ProxyConfig.SINGLETON_ID);
					assertThat(c.getHost()).isEqualTo("127.0.0.1");
				});

		// 第二次保存应覆盖原记录，全表仍仅一条
		ProxyConfig second = new ProxyConfig();
		second.setType(ProxyType.SOCKS);
		second.setHost("10.0.0.1");
		second.setPort(1080);
		second.setEnabled(true);
		second.setUsername("u");
		second.setPassword("p");
		proxyConfigService.save(second);

		// 非 IDENTITY 主键的 insert 延迟到 flush，count 前需手动 flush 让记录落库
		entityManager.flush();
		Integer count = jdbcTemplate.queryForObject("select count(*) from proxy_config", Integer.class);
		assertThat(count).isEqualTo(1);

		assertThat(proxyConfigService.getConfig())
				.isPresent()
				.get()
				.satisfies(c -> {
					assertThat(c.getType()).isEqualTo(ProxyType.SOCKS);
					assertThat(c.getHost()).isEqualTo("10.0.0.1");
					assertThat(c.getPort()).isEqualTo(1080);
				});
	}

	/** 验证代理密码落库为密文、读取时可逆还原为明文 */
	@Test
	@Transactional
	void proxyPasswordIsEncryptedAndReversible() {
		ProxyConfig cfg = new ProxyConfig();
		cfg.setType(ProxyType.HTTP);
		cfg.setHost("proxy.example.com");
		cfg.setPort(3128);
		cfg.setUsername("proxy-user");
		cfg.setPassword("proxy-secret");
		cfg.setEnabled(true);
		proxyConfigService.save(cfg);
		entityManager.flush();
		entityManager.clear();

		String dbPassword = jdbcTemplate.queryForObject(
				"select password from proxy_config where id = ?", String.class, ProxyConfig.SINGLETON_ID);
		assertThat(dbPassword).isNotEqualTo("proxy-secret");
		assertThat(aesEncryptor.decrypt(dbPassword)).isEqualTo("proxy-secret");

		ProxyConfig loaded = proxyConfigService.getConfig().orElseThrow();
		assertThat(loaded.getPassword()).isEqualTo("proxy-secret");
		assertThat(loaded.getUsername()).isEqualTo("proxy-user");
	}

	/** 验证 enabled 过滤：getEnabledConfig 仅在启用时返回配置 */
	@Test
	@Transactional
	void getEnabledConfigRespectsEnabledFlag() {
		ProxyConfig cfg = new ProxyConfig();
		cfg.setType(ProxyType.HTTP);
		cfg.setHost("127.0.0.1");
		cfg.setPort(8080);
		cfg.setEnabled(false);
		proxyConfigService.save(cfg);

		assertThat(proxyConfigService.getEnabledConfig()).isEmpty();

		cfg.setEnabled(true);
		proxyConfigService.save(cfg);

		assertThat(proxyConfigService.getEnabledConfig())
				.isPresent()
				.get()
				.satisfies(c -> assertThat(c.getHost()).isEqualTo("127.0.0.1"));
	}
}
