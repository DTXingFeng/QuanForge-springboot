package xyz.xingfeng.QuanForge;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

@SpringBootApplication
@EnableScheduling
public class QuanForgeSpringbootApplication {

	public static void main(String[] args) {
		ensureDataDirectory();
		SpringApplication.run(QuanForgeSpringbootApplication.class, args);
	}

	/**
	 * SQLite JDBC 不会创建父目录：默认数据源为相对路径 data/quanforge.db，
	 * 换工作目录启动（如 jar 部署）时需先确保 data/ 存在，否则 SQLITE_CANTOPEN。
	 */
	private static void ensureDataDirectory() {
		try {
			Files.createDirectories(Path.of("data"));
		} catch (IOException e) {
			throw new IllegalStateException("无法创建数据目录 data/: " + e.getMessage(), e);
		}
	}

}
