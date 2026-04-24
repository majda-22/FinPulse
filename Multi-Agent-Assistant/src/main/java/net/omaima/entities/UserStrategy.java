package net.omaima.entities;


import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;
import java.util.List;

@Entity
@Table(name = "user_strategies")
@Data
@NoArgsConstructor
@AllArgsConstructor
public class UserStrategy {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Column(nullable = false)
    private String companyTicker;

    @Column(nullable = false)
    private String companyName;

    @Column(nullable = false, columnDefinition = "TEXT")
    private String userArgument;

    private Double nciGlobal;

    private Double nciPersonalized;

    private Double fConsistency;

    @Column(columnDefinition = "TEXT")
    private String supportEvidence;  // JSON list

    @Column(columnDefinition = "TEXT")
    private String redFlags;  // JSON list

    private Double marketSentiment;

    @Column(columnDefinition = "TEXT")
    private String finalConclusion;

    private String pdfPath;

    @Column(nullable = false)
    private Boolean isActive = true;

    @Column(nullable = false)
    private LocalDateTime createdAt;

    @Column(nullable = false)
    private LocalDateTime lastUpdatedAt;

    @OneToMany(mappedBy = "userStrategy", cascade = CascadeType.ALL, orphanRemoval = true)
    private List<StrategyUpdateLog> updateLogs;

    @OneToMany(mappedBy = "relatedStrategy", cascade = CascadeType.DETACH, fetch = FetchType.LAZY)
    private List<ChatSession> relatedSessions;  // Sessions that reference this strategy
}