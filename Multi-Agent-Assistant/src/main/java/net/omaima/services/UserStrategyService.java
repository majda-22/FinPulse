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

/**
 * Service complet de gestion des stratégies d'investissement utilisateur
 */
@Service
@Slf4j
@RequiredArgsConstructor
public class UserStrategyService {

    private final UserStrategyRepository strategyRepository;
    private final StrategyUpdateLogRepository updateLogRepository;
    private final UserRepository userRepository;

    /**
     * Création d'une nouvelle stratégie (après validation par le rapport)
     */
    @Transactional
    public UserStrategy createStrategy(
            Long userId,
            String ticker,
            String companyName,
            String userArgument,
            Double nciGlobal,
            Double nciPersonalized,
            Double fConsistency,
            String supportEvidence,
            String redFlags,
            Double marketSentiment,
            String finalConclusion,
            String pdfPath) {

        log.info("createStrategy: user={}, ticker={}", userId, ticker);

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

        UserStrategy saved = strategyRepository.save(strategy);
        log.info("Stratégie créée: id={}", saved.getId());
        return saved;
    }

    /**
     * Mise à jour des métriques d'une stratégie existante
     * (utilisé par les jobs de monitoring)
     */
    @Transactional
    public void updateStrategy(
            Long strategyId,
            Double newNciPersonalized,
            Double priceChange,
            Double sentimentChange) {

        log.info("updateStrategy: id={}", strategyId);

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
        log.info("Stratégie mise à jour, alerte={}", alertTriggered);
    }

    /**
     * Détermine si une variation de NCI déclenche une alerte utilisateur
     */
    public boolean shouldTriggerAlert(Double oldNci, Double newNci) {
        if (oldNci == null || newNci == null) return false;
        double percentChange = Math.abs((newNci - oldNci) / oldNci * 100);
        double absoluteChange = Math.abs(newNci - oldNci);
        // Alerte si variation > 20% OU > 10 points
        return percentChange > 20 || absoluteChange > 10;
    }

    /**
     * Récupère TOUTES les stratégies actives de la plateforme
     * (usage interne pour dashboard admin, monitoring, etc.)
     */
    public List<UserStrategy> getActiveStrategies() {
        return strategyRepository.findByIsActiveTrue();
    }

    /**
     * Récupère UNIQUEMENT les stratégies actives d'un utilisateur spécifique
     * (appelé par ReportController /my-strategies)
     */
    public List<UserStrategy> getActiveStrategiesByUser(Long userId) {
        log.info("getActiveStrategiesByUser: userId={}", userId);
        return strategyRepository.findByUserIdAndIsActiveTrue(userId);
    }

    /**
     * Désactivation (soft delete) d'une stratégie
     */
    @Transactional
    public void deactivateStrategy(Long strategyId) {
        log.info("deactivateStrategy: id={}", strategyId);
        strategyRepository.findById(strategyId).ifPresent(strategy -> {
            strategy.setIsActive(false);
            strategy.setLastUpdatedAt(LocalDateTime.now());
            strategyRepository.save(strategy);
            log.info("Stratégie désactivée");
        });
    }

    /**
     * Historique des mises à jour d'une stratégie
     */
    public List<StrategyUpdateLog> getStrategyUpdateLogs(Long strategyId) {
        return updateLogRepository.findByUserStrategyId(strategyId);
    }

    /**
     * Suppression logique (mark as deleted)
     */
    @Transactional
    public void deleteStrategy(Long strategyId) {
        deactivateStrategy(strategyId);
    }
}