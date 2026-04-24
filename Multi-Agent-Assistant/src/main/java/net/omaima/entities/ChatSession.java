package net.omaima.entities;

import jakarta.persistence.*;
import jdk.jfr.DataAmount;
import lombok.*;
import java.time.LocalDateTime;
import java.util.List;

@Entity
@Table(name = "chat_sessions")
@Data
@NoArgsConstructor
@AllArgsConstructor
public class ChatSession {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Column(nullable = false)
    private String companyTicker;

    @Column(nullable = false)
    private String contextType;  // "AGENT" or "STRATEGY"

    @Column(nullable = false)
    private LocalDateTime startedAt;

    private LocalDateTime endedAt;

    private String sessionContext;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "related_strategy_id")
    private UserStrategy relatedStrategy;

    @OneToMany(mappedBy = "session", cascade = CascadeType.ALL, orphanRemoval = true)
    private List<ChatMessage> messages;
}