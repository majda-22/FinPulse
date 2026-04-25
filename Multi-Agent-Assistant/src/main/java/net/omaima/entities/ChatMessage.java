package net.omaima.entities;

import jakarta.persistence.*;
import jdk.jfr.DataAmount;
import lombok.*;
import java.time.LocalDateTime;
import java.util.List;

@Entity
@Table(name = "chat_messages")
@Data
@NoArgsConstructor
@AllArgsConstructor
public class ChatMessage {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "session_id", nullable = false)
    private ChatSession session;

    @Column(nullable = false)
    private String sender;  // "USER", "AI", "PHASE"

    @Column(nullable = false, columnDefinition = "TEXT")
    private String message;

    private String intent;  // INVESTMENT_STRATEGY, MARKET_QUERY, etc.

    private Double nciSnapshot;

    private Double confidenceScore;

    private String metadata;  // JSON

    @Column(nullable = false)
    private LocalDateTime createdAt;
}