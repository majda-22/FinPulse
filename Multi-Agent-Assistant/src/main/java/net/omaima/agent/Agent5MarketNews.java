package net.omaima.agent;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import net.omaima.services.IngestionPipelineService;
import org.springframework.stereotype.Service;
import java.util.ArrayList;
import java.util.List;

@Service
@Slf4j
@RequiredArgsConstructor
public class Agent5MarketNews {

    private final IngestionPipelineService ingestionPipelineService;

    public Double getPriceClose(String ticker) {
        log.info("Agent 5: Fetching price for {}", ticker);
        try {
            return ingestionPipelineService.getPriceClose(ticker);
        } catch (Exception e) {
            log.warn("Could not fetch price for {}", ticker);
            return null;
        }
    }

    public Double getSentimentScore(String ticker) {
        log.info("Agent 5: Fetching sentiment for {}", ticker);
        try {
            return ingestionPipelineService.getSentimentScore(ticker);
        } catch (Exception e) {
            log.warn("Could not fetch sentiment for {}", ticker);
            return 0.0;
        }
    }

    public List<String> getRecentNews(String ticker) {
        log.info("Agent 5: Fetching news for {}", ticker);
        return new ArrayList<>();
    }

    public List<PricePoint> getPriceHistory(String ticker, int days) {
        log.info("Agent 5: Fetching {} days of price history for {}", days, ticker);
        return new ArrayList<>();
    }

    public record PricePoint(String date, Double price) {}
}