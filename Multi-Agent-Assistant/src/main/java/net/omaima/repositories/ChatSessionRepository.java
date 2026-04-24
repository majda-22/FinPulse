package net.omaima.repositories;

import net.omaima.entities.ChatSession;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.List;

@Repository
public interface ChatSessionRepository extends JpaRepository<ChatSession, Long> {
    List<ChatSession> findByUserIdAndCompanyTickerOrderByStartedAtDesc(Long userId, String ticker);
    List<ChatSession> findByUserIdOrderByStartedAtDesc(Long userId);
    List<ChatSession> findByCompanyTickerOrderByStartedAtDesc(String ticker);
}