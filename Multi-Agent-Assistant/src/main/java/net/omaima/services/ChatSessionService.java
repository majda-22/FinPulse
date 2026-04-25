package net.omaima.services;

import jakarta.transaction.Transactional;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import net.omaima.entities.ChatMessage;
import net.omaima.entities.ChatSession;
import net.omaima.entities.User;
import net.omaima.repositories.ChatMessageRepository;
import net.omaima.repositories.ChatSessionRepository;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;
import java.util.regex.Pattern;


@Service
@Slf4j
@RequiredArgsConstructor
public class ChatSessionService {

    private final ChatSessionRepository sessionRepository;
    private final ChatMessageRepository messageRepository;

    @Transactional
    public ChatSession createSession(User user, String ticker, String contextType) {
        log.info("Creating chat session: user={}, ticker={}, type={}",
                user.getUsername(), ticker, contextType);

        ChatSession session = new ChatSession();
        session.setUser(user);
        session.setCompanyTicker(ticker);
        session.setContextType(contextType);
        session.setStartedAt(LocalDateTime.now());

        return sessionRepository.save(session);
    }

    @Transactional
    public ChatMessage saveMessage(ChatSession session, String sender, String message,
                                   String intent, Double nciSnapshot) {
        log.debug("Saving message: session={}, sender={}", session.getId(), sender);

        ChatMessage chatMessage = new ChatMessage();
        chatMessage.setSession(session);
        chatMessage.setSender(sender);
        chatMessage.setMessage(message);
        chatMessage.setIntent(intent);
        chatMessage.setNciSnapshot(nciSnapshot);
        chatMessage.setCreatedAt(LocalDateTime.now());

        return messageRepository.save(chatMessage);
    }

    public List<ChatMessage> getSessionHistory(Long sessionId) {
        return messageRepository.findBySessionIdOrderByCreatedAtAsc(sessionId);
    }

    public List<ChatSession> getUserSessionsForCompany(Long userId, String ticker) {
        return sessionRepository.findByUserIdAndCompanyTickerOrderByStartedAtDesc(userId, ticker);
    }

    @Transactional
    public void endSession(Long sessionId) {
        sessionRepository.findById(sessionId).ifPresent(session -> {
            session.setEndedAt(LocalDateTime.now());
            sessionRepository.save(session);
        });
    }

    public String detectIntent(String message) {
        if (Pattern.compile("rapport|pdf|analyse|stratégie", Pattern.CASE_INSENSITIVE).matcher(message).find()) {
            return "INVESTMENT_STRATEGY";
        }
        if (Pattern.compile("prix|price|stock|cours", Pattern.CASE_INSENSITIVE).matcher(message).find()) {
            return "MARKET_QUERY";
        }
        if (Pattern.compile("risque|risk|danger", Pattern.CASE_INSENSITIVE).matcher(message).find()) {
            return "RISK_ANALYSIS";
        }
        if (Pattern.compile("sentiment|news|média", Pattern.CASE_INSENSITIVE).matcher(message).find()) {
            return "SENTIMENT_QUERY";
        }
        return "GENERAL_QUERY";
    }
}
