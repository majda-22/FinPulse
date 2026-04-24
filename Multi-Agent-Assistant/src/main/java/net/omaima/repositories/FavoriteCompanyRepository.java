package net.omaima.repositories;

import net.omaima.entities.FavoriteCompany;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.List;
import java.util.Optional;

@Repository
public interface FavoriteCompanyRepository extends JpaRepository<FavoriteCompany, Long> {
    List<FavoriteCompany> findByUserIdOrderByAddedAtDesc(Long userId);
    Optional<FavoriteCompany> findByUserIdAndTicker(Long userId, String ticker);
}
