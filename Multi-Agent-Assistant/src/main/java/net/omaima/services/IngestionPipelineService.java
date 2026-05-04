package net.omaima.services;
//service qui a fait la communication avec une API liée à l’ingestion des données.

import java.util.Map;
import org.springframework.http.MediaType;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;

@Service
@Slf4j
@RequiredArgsConstructor
public class IngestionPipelineService {

    private final WebClient webClient;
    private final ObjectMapper objectMapper;

    @Value("${p1.api.url}")
    private String p1ApiUrl;

    //@Cacheable(value = "companyNames", key = "#ticker")
    public String getCompanyName(String ticker) {
        log.info("1- Fetching company name for {}", ticker);
        try {
            String response = webClient.get()
                    .uri("/api/v1/score/{ticker}/value/companies.name", ticker)
                    .retrieve()
                    .bodyToMono(String.class)
                    .block();

            log.info("API Response for {}: {}", ticker, response);

            // L'API retourne directement une chaîne : "Tesla, Inc."
            // Enlever les guillemets si présents
            if (response != null && response.startsWith("\"") && response.endsWith("\"")) {
                return response.substring(1, response.length() - 1);
            }
            return response;

        } catch (Exception e) {
            log.error("Error fetching company name for {}", ticker, e);
            return null;
        }
    }
    @Cacheable(value = "nciGlobal", key = "#ticker")
    public Double getNciGlobal(String ticker) {
        log.info("2- Fetching NCI Global for {}", ticker);
        try {
            String response = webClient.get()
                    .uri("/api/v1/score/{ticker}/value/companies.nci_global", ticker)
                    .retrieve()
                    .bodyToMono(String.class)
                    .block();

            return Double.parseDouble(response.trim());
        } catch (Exception e) {
            log.error("Error fetching NCI Global", e);
            throw new RuntimeException("Failed to fetch NCI Global", e);
        }
    }

    @Cacheable(value = "embeddingTexts", key = "#ticker + '-' + #chunkIdx")
    public String getLatestEmbeddingText(String ticker, int chunkIdx) {
        log.info("3- Fetching embedding text for {}", ticker);
        try {
            String response = webClient.get()
                    .uri("/api/v1/embeddings/{ticker}/latest/value/embeddings.text", ticker)
                    .retrieve()
                    .bodyToMono(String.class)
                    .block();

            // Enlever les guillemets si présents
            if (response != null && response.startsWith("\"") && response.endsWith("\"")) {
                return response.substring(1, response.length() - 1);
            }
            return response;
        } catch (Exception e) {
            log.error("Error fetching embedding text", e);
            throw new RuntimeException("Failed to fetch embedding text", e);
        }
    }

    @Cacheable(value = "filedAt", key = "#ticker")
    public String getLatestEmbeddingFiledAt(String ticker) {
        log.info("4- Fetching filed_at for {}", ticker);
        try {
            String response = webClient.get()
                    .uri("/api/v1/score/{ticker}/value/filings.filed_at", ticker)
                    .retrieve()
                    .bodyToMono(String.class)
                    .block();

            // Enlever les guillemets si présents
            if (response != null && response.startsWith("\"") && response.endsWith("\"")) {
                return response.substring(1, response.length() - 1);
            }
            return response;
        } catch (Exception e) {
            log.error("Error fetching filed_at", e);
            throw new RuntimeException("Failed to fetch filed_at", e);
        }
    }

    @Cacheable(value = "priceClose", key = "#ticker")
    public Double getPriceClose(String ticker) {
        log.info("5- Fetching price for {}", ticker);
        try {
            String response = webClient.get()
                    .uri("/api/v1/score/{ticker}/value/market_prices.price_close", ticker)
                    .retrieve()
                    .bodyToMono(String.class)
                    .block();

            return Double.parseDouble(response.trim());
        } catch (Exception e) {
            log.error("Error fetching price", e);
            return null;
        }
    }

    @Cacheable(value = "sentimentScore", key = "#ticker")
    public Double getSentimentScore(String ticker) {
        log.info("6- Fetching sentiment for {}", ticker);
        try {
            String response = webClient.get()
                    .uri("/api/v1/score/{ticker}/value/news_items.sentiment_score", ticker)
                    .retrieve()
                    .bodyToMono(String.class)
                    .block();

            return Double.parseDouble(response.trim());
        } catch (Exception e) {
            log.error("Error fetching sentiment", e);
            return 0.0;
        }
    }

    public String triggerBackfillPipeline(String ticker) {
        log.info("Triggering backfill pipeline for {}", ticker);
        try {
            Map<String, Object> body = new java.util.HashMap<>();
            body.put("symbol", ticker);
            body.put("identifier", ticker);
            body.put("ten_k_max", 3);
            body.put("ten_q_max", 4);
            body.put("form4_max", 20);
            body.put("form4_parse_limit", 20);
            body.put("news_limit", 50);
            body.put("run_signals", true);

            String response = webClient.post()
                    .uri("/api/v1/pipelines/backfill/company")
                    .contentType(MediaType.APPLICATION_JSON)
                    .bodyValue(body)
                    .retrieve()
                    .bodyToMono(String.class)
                    .block();

            log.info("Backfill response: {}", response);
            return response;
        } catch (Exception e) {
            log.error("Error triggering pipeline: {}", e.getMessage());
            throw new RuntimeException("Failed to trigger pipeline", e);
        }
    }}
