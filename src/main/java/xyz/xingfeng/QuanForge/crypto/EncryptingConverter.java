package xyz.xingfeng.QuanForge.crypto;

import jakarta.persistence.AttributeConverter;
import jakarta.persistence.Converter;

/**
 * JPA 属性转换器：写入数据库时加密，读取时解密还原明文。
 * 仅在实体字段显式 @Convert 指定时生效（autoApply = false）。
 */
@Converter
public class EncryptingConverter implements AttributeConverter<String, String> {

	@Override
	public String convertToDatabaseColumn(String attribute) {
		return AesEncryptor.getInstance().encrypt(attribute);
	}

	@Override
	public String convertToEntityAttribute(String dbData) {
		return AesEncryptor.getInstance().decrypt(dbData);
	}
}
