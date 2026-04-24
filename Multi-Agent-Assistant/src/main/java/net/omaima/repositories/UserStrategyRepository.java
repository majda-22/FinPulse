package net.omaima.repositories;

import net.omaima.entities.UserStrategy;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.List;
import java.util.Optional;

@Repository
public interface UserStrategyRepository extends JpaRepository<UserStrategy, Long> {
    List<UserStrategy> findByUserIdOrderByCreatedAtDesc(Long userId);
    List<UserStrategy> findByIsActiveTrue();
    List<UserStrategy> findByCompanyTickerAndIsActiveTrue(String ticker);
    Optional<UserStrategy> findByUserIdAndCompanyTicker(Long userId, String ticker);
    List<UserStrategy> findByUserIdAndIsActiveTrue(Long userId);
}