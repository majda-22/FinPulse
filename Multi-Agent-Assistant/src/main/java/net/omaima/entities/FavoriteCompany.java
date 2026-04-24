package net.omaima.entities;

import jakarta.persistence.*;
import jdk.jfr.DataAmount;
import lombok.*;
import java.time.LocalDateTime;
import java.util.List;


@Entity
@Table(name = "favorite_companies")
@Data
@NoArgsConstructor
@AllArgsConstructor
public class FavoriteCompany {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Column(nullable = false)
    private String ticker;

    @Column(nullable = false)
    private String companyName;

    @Column(nullable = false)
    private LocalDateTime addedAt;
}