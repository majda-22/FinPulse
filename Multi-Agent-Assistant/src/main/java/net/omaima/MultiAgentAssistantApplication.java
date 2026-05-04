package net.omaima;
import io.github.cdimascio.dotenv.Dotenv;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cache.annotation.EnableCaching;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableCaching
@EnableScheduling

public class MultiAgentAssistantApplication {

    public static void main(String[] args) {
        Dotenv dotenv = Dotenv.configure().load();
        System.setProperty("MISTRAL_API_KEY", dotenv.get("MISTRAL_API_KEY"));
        SpringApplication.run(MultiAgentAssistantApplication.class, args);
    }

}
