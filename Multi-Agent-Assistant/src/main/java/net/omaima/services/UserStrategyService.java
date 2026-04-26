package net.omaima.services;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import net.omaima.entities.StrategyUpdateLog;
import net.omaima.entities.User;
import net.omaima.entities.UserStrategy;
import net.omaima.repositories.StrategyUpdateLogRepository;
import net.omaima.repositories.UserRepository;
import net.omaima.repositories.UserStrategyRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

@Service
@Slf4j
@RequiredArgsConstructor
public class UserStrategyService {

    private final UserStrategyRepository strategyRepository;
    private final StrategyUpdateLogRepository updateLogRepository;
    private final UserRepository userRepository;

    @Transactional
    public UserStrategy createStrategy(
            Long userId, String ticker, String companyName, String userArgument,
            Double nciGlobal, Double nciPersonalized, Double fConsistency,
            String supportEvidence, String redFlags, Double marketSentiment,
            String finalConclusion, String pdfPath) {

        log.info("Création stratégie: user={}, ticker={}", userId, ticker);

        User user = userRepository.findById(userId)
                .orElseThrow(() -> new RuntimeException("Utilisateur introuvable: " + userId));

        UserStrategy strategy = new UserStrategy();
        strategy.setUser(user);
        strategy.setCompanyTicker(ticker);
        strategy.setCompanyName(companyName);
        strategy.setUserArgument(userArgument);
        strategy.setNciGlobal(nciGlobal);
        strategy.setNciPersonalized(nciPersonalized);
        strategy.setFConsistency(fConsistency);
        strategy.setSupportEvidence(supportEvidence);
        strategy.setRedFlags(redFlags);
        strategy.setMarketSentiment(marketSentiment);
        strategy.setFinalConclusion(finalConclusion);
        strategy.setPdfPath(pdfPath);
        strategy.setIsActive(true);
        strategy.setCreatedAt(LocalDateTime.now());
        strategy.setLastUpdatedAt(LocalDateTime.now());

        return strategyRepository.save(strategy);
    }

    @Transactional
    public void updateStrategy(Long strategyId, Double newNciPersonalized,
                               Double priceChange, Double sentimentChange) {

        log.info("Mise à jour stratégie: id={}", strategyId);

        UserStrategy strategy = strategyRepository.findById(strategyId)
                .orElseThrow(() -> new RuntimeException("Stratégie introuvable: " + strategyId));

        Double oldNci = strategy.getNciPersonalized();
        strategy.setNciPersonalized(newNciPersonalized);
        strategy.setLastUpdatedAt(LocalDateTime.now());
        strategyRepository.save(strategy);

        boolean alertTriggered = shouldTriggerAlert(oldNci, newNciPersonalized);

        StrategyUpdateLog updateLog = new StrategyUpdateLog();
        updateLog.setUserStrategy(strategy);
        updateLog.setPreviousNciPersonalized(oldNci);
        updateLog.setNewNciPersonalized(newNciPersonalized);
        updateLog.setPriceChangePercent(priceChange);
        updateLog.setSentimentChange(sentimentChange);
        updateLog.setAlertTriggered(alertTriggered);
        updateLog.setCreatedAt(LocalDateTime.now());

        updateLogRepository.save(updateLog);
    }

    public boolean shouldTriggerAlert(Double oldNci, Double newNci) {
        if (oldNci == null || newNci == null) return false;
        double percentChange = Math.abs((newNci - oldNci) / oldNci * 100);
        double absoluteChange = Math.abs(newNci - oldNci);
        return percentChange > 20 || absoluteChange > 10;
    }

    /** Toutes les stratégies actives de la plateforme (usage interne/admin) */
    public List<UserStrategy> getActiveStrategies() {
        return strategyRepository.findByIsActiveTrue();
    }

    /**
     * stratégies filtrées par utilisateur.
     * Utilisée par ReportController pour /my-strategies.
     */
    public List<UserStrategy> getActiveStrategiesByUser(Long userId) {
        return strategyRepository.findByUserIdAndIsActiveTrue(userId);
    }

    @Transactional
    public void deactivateStrategy(Long strategyId) {
        log.info("Désactivation stratégie: {}", strategyId);
        strategyRepository.findById(strategyId).ifPresent(strategy -> {
            strategy.setIsActive(false);
            strategyRepository.save(strategy);
        });
    }

    public List<StrategyUpdateLog> getStrategyUpdateLogs(Long strategyId) {
        return updateLogRepository.findByUserStrategyId(strategyId);
    }
}