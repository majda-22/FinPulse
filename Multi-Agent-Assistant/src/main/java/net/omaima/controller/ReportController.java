package net.omaima.controller;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import net.omaima.entities.User;
import net.omaima.services.JwtTokenProvider;
import net.omaima.services.MultiAgentOrchestrator;
import net.omaima.services.UserStrategyService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.List;



@RestController
@RequestMapping("/api/v2/strategy")
@RequiredArgsConstructor
@Slf4j
public class ReportController {

    private final UserStrategyService strategyService;
    private final JwtTokenProvider jwtTokenProvider;
    private final MultiAgentOrchestrator orchestrator;

    record StrategyDTO(
            Long id, String ticker, String companyName, String userArgument,
            Double nciGlobal, Double nciPersonalized, Double fConsistency,
            Boolean isActive, LocalDateTime createdAt
    ) {}

    // =====================================================================
    // ENREGISTRER UNE STRATÉGIE
    // =====================================================================

    /**
     * Endpoint appelé par le frontend quand l'utilisateur
     * clique sur "Enregistrer la stratégie" après avoir vu le rapport.
     *
     * Le frontend envoie les données calculées par l'orchestrateur.
     * Cette méthode les sauvegarde en base de données.
     */
    record SaveStrategyRequest(
            String  ticker,
            String  companyName,
            String  userArgument,
            Double  nciGlobal,
            Double  nciPersonalized,
            Double  fConsistency,
            Double  sentiment,
            String  supportEvidence,
            String  redFlags,
            String  finalConclusion
    ) {}

    record SaveStrategyResponse(
            boolean success,
            Long    strategyId,
            String  message
    ) {}

    @PostMapping("/save")
    public ResponseEntity<SaveStrategyResponse> saveStrategy(
            @RequestHeader("Authorization") String authHeader,
            @RequestBody SaveStrategyRequest request) {

        log.info("POST /strategy/save — ticket={}", request.ticker());

        try {
            String token = authHeader.replace("Bearer ", "");
            User user = jwtTokenProvider.getUserFromToken(token);

            // Sauvegarde en base
            var strategy = strategyService.createStrategy(
                    user.getId(),
                    request.ticker(),
                    request.companyName(),
                    request.userArgument(),
                    request.nciGlobal(),
                    request.nciPersonalized(),
                    request.fConsistency(),
                    request.supportEvidence(),
                    request.redFlags(),
                    request.sentiment(),
                    request.finalConclusion(),
                    null // path PDF non utilisé côté serveur
            );

            log.info("Stratégie enregistrée: id={}, user={}", strategy.getId(), user.getUsername());

            return ResponseEntity.ok(new SaveStrategyResponse(
                    true,
                    strategy.getId(),
                    "Stratégie enregistrée avec succès"
            ));

        } catch (Exception e) {
            log.error("Erreur sauvegarde stratégie", e);
            return ResponseEntity.internalServerError()
                    .body(new SaveStrategyResponse(false, null, e.getMessage()));
        }
    }

    // =====================================================================
    // CONSULTER LES STRATÉGIES DE L'UTILISATEUR
    // =====================================================================

    @GetMapping("/my-strategies")
    public ResponseEntity<List<StrategyDTO>> getUserStrategies(
            @RequestHeader("Authorization") String authHeader) {

        try {
            String token = authHeader.replace("Bearer ", "");
            User user = jwtTokenProvider.getUserFromToken(token);

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

    // =====================================================================
    // DÉSACTIVER UNE STRATÉGIE
    // =====================================================================

    @DeleteMapping("/{strategyId}")
    public ResponseEntity<String> deactivateStrategy(
            @RequestHeader("Authorization") String authHeader,
            @PathVariable Long strategyId) {

        try {
            String token = authHeader.replace("Bearer ", "");
            User user = jwtTokenProvider.getUserFromToken(token);

            // Vérifier propriété
            boolean owned = strategyService.getActiveStrategiesByUser(user.getId())
                    .stream().anyMatch(s -> s.getId().equals(strategyId));

            if (!owned) {
                return ResponseEntity.status(403).body("Accès refusé");
            }

            strategyService.deactivateStrategy(strategyId);
            return ResponseEntity.ok("Stratégie désactivée");

        } catch (Exception e) {
            log.error("Erreur désactivation", e);
            return ResponseEntity.internalServerError().build();
        }
    }
}