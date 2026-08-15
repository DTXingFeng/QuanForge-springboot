package xyz.xingfeng.QuanForge.crypto;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Base64;

/**
 * AES-GCM 可逆加解密工具。
 * 落库时加密、读取时解密，调用外部 API 时仍可还原明文。
 */
@Component
public class AesEncryptor {

	private static final String TRANSFORMATION = "AES/GCM/NoPadding";
	private static final int IV_LENGTH = 12;  // GCM 推荐 12 字节 IV
	private static final int TAG_BITS = 128;  // 认证标签位数

	/** 静态实例：供非 Spring 管理的 AttributeConverter 访问 */
	private static volatile AesEncryptor instance;

	private final SecretKey secretKey;
	private final SecureRandom random = new SecureRandom();

	public AesEncryptor(@Value("${app.crypto.key}") String base64Key) {
		byte[] keyBytes = Base64.getDecoder().decode(base64Key);
		this.secretKey = new SecretKeySpec(keyBytes, "AES");
		instance = this;
	}

	/** 获取全局实例 */
	public static AesEncryptor getInstance() {
		if (instance == null) {
			throw new IllegalStateException("AesEncryptor 尚未初始化");
		}
		return instance;
	}

	/** 加密：返回 Base64(IV + 密文 + 认证标签) */
	public String encrypt(String plain) {
		if (plain == null) {
			return null;
		}
		try {
			byte[] iv = new byte[IV_LENGTH];
			random.nextBytes(iv);

			Cipher cipher = Cipher.getInstance(TRANSFORMATION);
			cipher.init(Cipher.ENCRYPT_MODE, secretKey, new GCMParameterSpec(TAG_BITS, iv));
			byte[] cipherText = cipher.doFinal(plain.getBytes(StandardCharsets.UTF_8));

			byte[] combined = new byte[iv.length + cipherText.length];
			System.arraycopy(iv, 0, combined, 0, iv.length);
			System.arraycopy(cipherText, 0, combined, iv.length, cipherText.length);
			return Base64.getEncoder().encodeToString(combined);
		} catch (Exception e) {
			throw new IllegalStateException("加密失败", e);
		}
	}

	/** 解密：还原明文 */
	public String decrypt(String token) {
		if (token == null) {
			return null;
		}
		try {
			byte[] combined = Base64.getDecoder().decode(token);
			byte[] iv = Arrays.copyOfRange(combined, 0, IV_LENGTH);
			byte[] cipherText = Arrays.copyOfRange(combined, IV_LENGTH, combined.length);

			Cipher cipher = Cipher.getInstance(TRANSFORMATION);
			cipher.init(Cipher.DECRYPT_MODE, secretKey, new GCMParameterSpec(TAG_BITS, iv));
			return new String(cipher.doFinal(cipherText), StandardCharsets.UTF_8);
		} catch (Exception e) {
			throw new IllegalStateException("解密失败", e);
		}
	}
}
