package net.omaima.config;

import io.netty.channel.ChannelOption;
import io.netty.handler.timeout.ReadTimeoutHandler;
import io.netty.handler.timeout.WriteTimeoutHandler;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import java.util.concurrent.TimeUnit;

@Configuration
@Slf4j
public class WebClientConfig {

    @Value("${p1.api.url}")
    private String p1ApiUrl;

    @Bean
    public WebClient webClient() {

        log.info("Configuring WebClient for P1 API: {}", p1ApiUrl);

        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, 10000)
                .option(ChannelOption.SO_KEEPALIVE, true)
                .responseTimeout(java.time.Duration.ofSeconds(30))
                .doOnConnected(conn -> conn
                        .addHandlerLast(new ReadTimeoutHandler(30, TimeUnit.SECONDS))
                        .addHandlerLast(new WriteTimeoutHandler(30, TimeUnit.SECONDS)));

        return WebClient.builder()
                .baseUrl(p1ApiUrl)
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .build();
    }

    @Bean
    public com.fasterxml.jackson.databind.ObjectMapper objectMapper() {
        return new com.fasterxml.jackson.databind.ObjectMapper();
    }
}