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

        log.info("Creating strategy: user={}, ticker={}", userId, ticker);

        User user = userRepository.findById(userId)
                .orElseThrow(() -> new RuntimeException("User not found"));

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

        log.info("Updating strategy: id={}", strategyId);

        UserStrategy strategy = strategyRepository.findById(strategyId)
                .orElseThrow(() -> new RuntimeException("Strategy not found"));

        Double oldNci = strategy.getNciPersonalized();
        strategy.setNciPersonalized(newNciPersonalized);
        strategy.setLastUpdatedAt(LocalDateTime.now());
        strategyRepository.save(strategy);

        boolean alertTriggered = shouldTriggerAlert(oldNci, newNciPersonalized);

        StrategyUpdateLog log = new StrategyUpdateLog();
        log.setUserStrategy(strategy);
        log.setPreviousNciPersonalized(oldNci);
        log.setNewNciPersonalized(newNciPersonalized);
        log.setPriceChangePercent(priceChange);
        log.setSentimentChange(sentimentChange);
        log.setAlertTriggered(alertTriggered);
        log.setCreatedAt(LocalDateTime.now());

        updateLogRepository.save(log);
    }

    public boolean shouldTriggerAlert(Double oldNci, Double newNci) {
        if (oldNci == null || newNci == null) return false;

        double percentChange = Math.abs((newNci - oldNci) / oldNci * 100);
        double absoluteChange = Math.abs(newNci - oldNci);

        return percentChange > 20 || absoluteChange > 10;
    }

    public List<UserStrategy> getActiveStrategies() {
        return strategyRepository.findByIsActiveTrue();
    }

    @Transactional
    public void deactivateStrategy(Long strategyId) {
        log.info("Deactivating strategy: {}", strategyId);
        strategyRepository.findById(strategyId).ifPresent(strategy -> {
            strategy.setIsActive(false);
            strategyRepository.save(strategy);
        });
    }

    public List<StrategyUpdateLog> getStrategyUpdateLogs(Long strategyId) {
        return updateLogRepository.findByUserStrategyId(strategyId);
    }
}