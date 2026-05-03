package net.omaima.controller;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import net.omaima.entities.User;
import net.omaima.services.JwtTokenProvider;
import net.omaima.services.MultiAgentOrchestrator;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 *gère les 3 modes de réponse de l'orchestrateur
 * - CHATBOT : JSON texte
 * - CLARIFICATION : JSON question
 * - REPORT : PDF binaire + données JSON
 */
@RestController
@RequestMapping("/api/v2/assistant")
@RequiredArgsConstructor
@Slf4j
public class ChatController {

    private final MultiAgentOrchestrator orchestrator;
    private final JwtTokenProvider jwtTokenProvider;

    record ChatRequest(String message, String ticker) {}

    record ChatResponse(
            String  message,
            boolean success,
            String  mode,
            String  error
    ) {}

    /**
     * Point d'entrée unique pour tous les modes.
     * Retourne différents types de réponse selon le résultat.
     */
    @PostMapping("/chat")
    public ResponseEntity<?> chat(
            @RequestHeader("Authorization") String authHeader,
            @RequestBody ChatRequest request) {

        log.info("POST /chat — ticker={} message={}", request.ticker(), request.message());

        try {
            String token = authHeader.replace("Bearer ", "");
            User user = jwtTokenProvider.getUserFromToken(token);

            // Orchestre tout
            MultiAgentOrchestrator.OrchestratorResult result =
                    orchestrator.handleMessage(user, request.ticker(), request.message());

            return switch (result.mode()) {
                // Mode chatbot : simple réponse texte en JSON
                case CHATBOT -> ResponseEntity.ok(
                        new ChatResponse(result.textResponse(), true, "CHATBOT", null)
                );

                // Clarification : question posée à l'utilisateur
                case NEEDS_CLARIFICATION -> ResponseEntity.ok(
                        new ChatResponse(result.textResponse(), true, "CLARIFICATION", null)
                );

                // Mode rapport : retourner le PDF + les données calculées dans les headers
                case REPORT -> {
                    MultiAgentOrchestrator.ReportResult report = result.reportResult();

                    yield ResponseEntity.ok()
                            .header(HttpHeaders.CONTENT_DISPOSITION,
                                    "attachment; filename=rapport_" + report.ticker() + ".pdf")
                            .header("X-Report-Ticker", report.ticker())
                            .header("X-Report-Company", report.companyName())
                            .header("X-NCI-Global", String.valueOf(report.nciGlobal()))
                            .header("X-NCI-Personalized", String.valueOf(report.nciPersonalized()))
                            .header("X-F-Consistency", String.valueOf(report.fConsistency()))
                            .header("X-Sentiment", String.valueOf(report.sentiment()))
                            // Les chaînes de caractères ne passent pas bien en headers, donc
                            // on les répartit dans des classes JSON en bas de la réponse
                            .contentType(MediaType.APPLICATION_PDF)
                            .body(report.pdfBytes());
                }

                // Hors sujet : traité comme clarification
                default -> ResponseEntity.ok(
                        new ChatResponse(result.textResponse(), true, "OUT_OF_SCOPE", null)
                );
            };

        } catch (Exception e) {
            log.error("Erreur /chat", e);
            return ResponseEntity.internalServerError()
                    .body(new ChatResponse(null, false, null, e.getMessage()));
        }
    }

    /**
     * Endpoint alternatif pour obtenir le JSON complet du rapport
     * (au lieu du PDF binaire).
     *
     * Utile si le frontend veut afficher les métadonnées avant téléchargement,
     * ou pour générer plusieurs formats.
     *
     * Appelé APRÈS /chat pour récupérer les données de la génération.
     * À encapsuler dans un cache côté orchestrateur si nécessaire.
     */
    record ReportMetadataRequest(String ticker, String userArgument) {}

    record ReportMetadataResponse(
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

    @PostMapping("/report-metadata")
    public ResponseEntity<?> getReportMetadata(
            @RequestHeader("Authorization") String authHeader,
            @RequestBody ReportMetadataRequest request) {

        log.info("POST /report-metadata — ticket={}", request.ticker());

        try {
            String token = authHeader.replace("Bearer ", "");
            User user = jwtTokenProvider.getUserFromToken(token);

            // Génère le rapport (sans le sauvegarder)
            MultiAgentOrchestrator.ReportResult report =
                    orchestrator.generateStrategyReport(user, request.ticker(), request.userArgument());

            return ResponseEntity.ok(new ReportMetadataResponse(
                    report.ticker(),
                    report.companyName(),
                    report.userArgument(),
                    report.nciGlobal(),
                    report.nciPersonalized(),
                    report.fConsistency(),
                    report.sentiment(),
                    report.supportEvidence(),
                    report.redFlags(),
                    report.finalConclusion()
            ));

        } catch (Exception e) {
            log.error("Erreur /report-metadata", e);
            return ResponseEntity.internalServerError()
                    .body(new ChatResponse(null, false, null, e.getMessage()));
        }
    }

    /**
     *Check si une entreprise existe (avec backfill si besoin)
     */
    record CompanyCheckRequest(String ticker) {}

    record CompanyCheckResponse(
            boolean exists,
            String  message,
            String  status
    ) {}

    @PostMapping("/check-company")
    public ResponseEntity<CompanyCheckResponse> checkCompany(
            @RequestHeader("Authorization") String authHeader,
            @RequestBody CompanyCheckRequest request) {

        log.info("POST /check-company — ticker={}", request.ticker());

        try {
            String token = authHeader.replace("Bearer ", "");
            jwtTokenProvider.getUserFromToken(token); // validation auth

            boolean exists = orchestrator.checkIfCompanyExists(request.ticker());

            if (!exists) {
                return ResponseEntity.ok(new CompanyCheckResponse(
                        false,
                        "L'entreprise " + request.ticker() + " n'est pas encore disponible. " +
                                "Ingestion en cours...",
                        "PENDING"
                ));
            }

            return ResponseEntity.ok(new CompanyCheckResponse(
                    true,
                    "Entreprise disponible",
                    null
            ));

        } catch (Exception e) {
            log.error("Erreur /check-company", e);
            return ResponseEntity.internalServerError()
                    .body(new CompanyCheckResponse(false, e.getMessage(), null));
        }
    }
}