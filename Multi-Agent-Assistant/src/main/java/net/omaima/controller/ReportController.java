package net.omaima.controller;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import net.omaima.entities.User;
import net.omaima.services.JwtTokenProvider;
import net.omaima.services.UserStrategyService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.List;

/*
 *
 *
 * Note: la génération de rapport est maintenant gérée par ChatController
 * via l'orchestrateur unifié. Ce controller gère uniquement la consultation.
 */
@RestController
@RequestMapping("/api/v2/strategy")
@RequiredArgsConstructor
@Slf4j
public class ReportController {

    private final UserStrategyService strategyService;
    private final JwtTokenProvider jwtTokenProvider;

    record StrategyDTO(
            Long id, String ticker, String companyName, String userArgument,
            Double nciGlobal, Double nciPersonalized, Double fConsistency,
            Boolean isActive, LocalDateTime createdAt
    ) {}


    @GetMapping("/my-strategies")
    public ResponseEntity<List<StrategyDTO>> getUserStrategies(
            @RequestHeader("Authorization") String authHeader) {

        try {
            String token = authHeader.replace("Bearer ", "");
            User user = jwtTokenProvider.getUserFromToken(token);

            // ✅ Filtré par user.getId()
            List<StrategyDTO> dtos = strategyService
                    .getActiveStrategiesByUser(user.getId())
                    .stream()
                    .map(s -> new StrategyDTO(
                            s.getId(), s.getCompanyTicker(), s.getCompanyName(),
                            s.getUserArgument(), s.getNciGlobal(), s.getNciPersonalized(),
                            s.getFConsistency(), s.getIsActive(), s.getCreatedAt()))
                    .toList();

            return ResponseEntity.ok(dtos);

        } catch (Exception e) {
            log.error("Erreur récupération stratégies", e);
            return ResponseEntity.internalServerError().build();
        }
    }

    @DeleteMapping("/{strategyId}")
    public ResponseEntity<String> deactivateStrategy(
            @RequestHeader("Authorization") String authHeader,
            @PathVariable Long strategyId) {

        try {
            String token = authHeader.replace("Bearer ", "");
            User user = jwtTokenProvider.getUserFromToken(token);

            // ✅ Vérifier que la stratégie appartient bien à cet user
            boolean owned = strategyService.getActiveStrategiesByUser(user.getId())
                    .stream().anyMatch(s -> s.getId().equals(strategyId));

            if (!owned) {
                return ResponseEntity.status(403).body("Accès refusé à cette stratégie");
            }

            strategyService.deactivateStrategy(strategyId);
            return ResponseEntity.ok("Stratégie désactivée");

        } catch (Exception e) {
            log.error("Erreur désactivation stratégie", e);
            return ResponseEntity.internalServerError().build();
        }
    }
}