package net.omaima.config;

import io.netty.channel.ChannelOption;
import io.netty.handler.timeout.ReadTimeoutHandler;
import io.netty.handler.timeout.WriteTimeoutHandler;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.ClientRequest;
import org.springframework.web.reactive.function.client.ExchangeFilterFunction;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;
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

        //Ce filtre copie le token JWT de la requête entrante vers l'appel API P1
        ExchangeFilterFunction jwtPropagationFilter = (request, next) -> {
            try {
                ServletRequestAttributes attrs =
                        (ServletRequestAttributes) RequestContextHolder.getRequestAttributes();
                if (attrs != null) {
                    String authHeader = attrs.getRequest().getHeader("Authorization");
                    if (authHeader != null && authHeader.startsWith("Bearer ")) {
                        request = ClientRequest.from(request)
                                .header("Authorization", authHeader)
                                .build();
                    }
                }
            } catch (Exception e) {
                log.warn("Could not propagate JWT token: {}", e.getMessage());
            }
            return next.exchange(request);
        };

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
                .filter(jwtPropagationFilter)  // ← AJOUTÉ
                .build();
    }

    @Bean
    public com.fasterxml.jackson.databind.ObjectMapper objectMapper() {
        return new com.fasterxml.jackson.databind.ObjectMapper();
    }
}