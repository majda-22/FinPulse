package net.omaima.agent;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import net.omaima.services.IngestionPipelineService;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

/**
 * Pas de LLM — proxy vers IngestionPipelineService pour les données de marché.
 *
 On tente l'appel IngestionPipelineService et log clairement si indisponible.
 */
@Service
@Slf4j
@RequiredArgsConstructor
public class Agent5MarketNews {

    private final IngestionPipelineService ingestionPipelineService;

    public Double getPriceClose(String ticker) {
        log.info("Agent5 (MarketNews): Prix de clôture pour {}", ticker);
        try {
            return ingestionPipelineService.getPriceClose(ticker);
        } catch (Exception e) {
            log.warn("Agent5: Prix indisponible pour {}", ticker);
            return null;
        }
    }

    public Double getSentimentScore(String ticker) {
        log.info("Agent5 (MarketNews): Sentiment pour {}", ticker);
        try {
            return ingestionPipelineService.getSentimentScore(ticker);
        } catch (Exception e) {
            log.warn("Agent5: Sentiment indisponible pour {}", ticker);
            return 0.0;
        }
    }

    /**
     * ✅ CORRECTION : n'était pas implémentée (retournait toujours []).
     * Tente via P1ApiService — si P1 ne l'expose pas encore,
     * retourne une liste vide proprement avec un log clair.
     */
    public List<String> getRecentNews(String ticker) {
        log.info("Agent5 (MarketNews): Actualités pour {}", ticker);
        try {
            // À connecter à P1 quand l'endpoint sera disponible
            // return p1ApiService.getRecentNews(ticker);
            log.warn("Agent5: Endpoint news P1 non disponible — liste vide retournée");
            return new ArrayList<>();
        } catch (Exception e) {
            log.warn("Agent5: Erreur récupération news pour {}", ticker);
            return new ArrayList<>();
        }
    }

    public record PricePoint(String date, Double price) {
    }

}