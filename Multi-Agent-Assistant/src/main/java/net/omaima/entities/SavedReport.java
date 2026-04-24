package net.omaima.entities;

import jakarta.persistence.*;
import lombok.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "saved_reports")
@Data
@NoArgsConstructor
@AllArgsConstructor
public class SavedReport {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Column(nullable = false)
    private String ticker;

    @Column(columnDefinition = "TEXT")
    private String userArgument;

    private String pdfPath;

    private Double nciPersonalized;

    @Column(nullable = false)
    private LocalDateTime createdAt;
}