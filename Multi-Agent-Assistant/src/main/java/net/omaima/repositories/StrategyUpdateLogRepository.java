package net.omaima.repositories;

import net.omaima.entities.StrategyUpdateLog;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.List;

@Repository
public interface StrategyUpdateLogRepository extends JpaRepository<StrategyUpdateLog, Long> {
    List<StrategyUpdateLog> findByUserStrategyId(Long userStrategyId);
    List<StrategyUpdateLog> findByUserStrategyIdOrderByCreatedAtDesc(Long userStrategyId);
    List<StrategyUpdateLog> findByAlertTriggeredTrue();
}