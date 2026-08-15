package xyz.xingfeng.QuanForge;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class QuanForgeSpringbootApplication {

	public static void main(String[] args) {
		SpringApplication.run(QuanForgeSpringbootApplication.class, args);
	}

}
