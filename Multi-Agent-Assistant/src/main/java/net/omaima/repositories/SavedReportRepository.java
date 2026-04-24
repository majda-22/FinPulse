package net.omaima.repositories;

import net.omaima.entities.SavedReport;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.List;
import java.util.Optional;

@Repository
public interface SavedReportRepository extends JpaRepository<SavedReport, Long> {
    List<SavedReport> findByUserIdOrderByCreatedAtDesc(Long userId);
    Optional<SavedReport> findByUserIdAndTicker(Long userId, String ticker);
    List<SavedReport> findByTicker(String ticker);
}