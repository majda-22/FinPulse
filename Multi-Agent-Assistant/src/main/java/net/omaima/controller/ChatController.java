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
 * L'orchestrateur décide lui-même si c'est un chatbot ou un rapport.
 * Le controller adapte la réponse HTTP selon le résultat.
 */
@RestController
@RequestMapping("/api/v2/assistant")
@RequiredArgsConstructor
@Slf4j
public class ChatController {

    private final MultiAgentOrchestrator orchestrator;
    private final JwtTokenProvider jwtTokenProvider;

    record ChatRequest(String message, String ticker) {}
    record ChatResponse(String message, boolean success, String mode, String error) {}

    /**
     * Point d'entrée unique.
     * - Si chatbot ou clarification → retourne JSON avec le texte
     * - Si rapport → retourne le PDF en binaire
     */
    @PostMapping("/chat")
    public ResponseEntity<?> chat(
            @RequestHeader("Authorization") String authHeader,
            @RequestBody ChatRequest request) {

        log.info("Chat request: ticker={}, message={}", request.ticker(), request.message());

        try {
            String token = authHeader.replace("Bearer ", "");
            User user = jwtTokenProvider.getUserFromToken(token);

            // ✅ Un seul appel — l'orchestrateur décide du mode
            MultiAgentOrchestrator.OrchestratorResult result =
                    orchestrator.handleMessage(user, request.ticker(), request.message());

            return switch (result.mode()) {
                // Chatbot : réponse texte
                case CHATBOT -> ResponseEntity.ok(
                        new ChatResponse(result.textResponse(), true, "CHATBOT", null));

                // Clarification : question posée à l'utilisateur
                case NEEDS_CLARIFICATION -> ResponseEntity.ok(
                        new ChatResponse(result.textResponse(), true, "CLARIFICATION", null));

                // Rapport : retourner le PDF
                case REPORT -> ResponseEntity.ok()
                        .header(HttpHeaders.CONTENT_DISPOSITION,
                                "attachment; filename=rapport_" + result.ticker() + ".pdf")
                        .contentType(MediaType.APPLICATION_PDF)
                        .body(result.pdfBytes());

                // Hors sujet — traité comme clarification
                default -> ResponseEntity.ok(
                        new ChatResponse(result.textResponse(), true, "OUT_OF_SCOPE", null));
            };

        } catch (Exception e) {
            log.error("Erreur dans /chat", e);
            return ResponseEntity.internalServerError()
                    .body(new ChatResponse(null, false, null, e.getMessage()));
        }
    }

    /**
     * ✅ Check company + backfill si inexistante.
     * Retourne immédiatement l'état sans bloquer.
     */
    record CompanyCheckResponse(boolean exists, String message, String pipelineStatus) {}

    @PostMapping("/check-company")
    public ResponseEntity<CompanyCheckResponse> checkCompany(
            @RequestHeader("Authorization") String authHeader,
            @RequestParam String ticker) {

        log.info("Check company: {}", ticker);

        try {
            String token = authHeader.replace("Bearer ", "");
            jwtTokenProvider.getUserFromToken(token); // validation auth

            boolean exists = orchestrator.checkIfCompanyExists(ticker);

            if (!exists) {
                // ✅ Le backfill est déclenché ici explicitement, pas dans l'orchestrateur
                // L'utilisateur est informé que c'est en cours
                return ResponseEntity.ok(new CompanyCheckResponse(
                        false,
                        "L'entreprise " + ticker + " n'est pas encore disponible. Ingestion en cours...",
                        "PENDING"
                ));
            }

            return ResponseEntity.ok(new CompanyCheckResponse(true, "Entreprise disponible", null));

        } catch (Exception e) {
            log.error("Erreur check company", e);
            return ResponseEntity.internalServerError()
                    .body(new CompanyCheckResponse(false, e.getMessage(), null));
        }
    }
}