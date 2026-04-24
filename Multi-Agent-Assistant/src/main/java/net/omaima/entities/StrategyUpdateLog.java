package net.omaima.entities;


import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "strategy_update_logs")
@Data
@NoArgsConstructor
@AllArgsConstructor
public class StrategyUpdateLog {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_strategy_id", nullable = false)
    private UserStrategy userStrategy;

    private Double previousNciPersonalized;

    private Double newNciPersonalized;

    private Double priceChangePercent;

    private Double sentimentChange;

    private String updateReason;

    private Boolean alertTriggered = false;

    @Column(nullable = false)
    private LocalDateTime createdAt;
}