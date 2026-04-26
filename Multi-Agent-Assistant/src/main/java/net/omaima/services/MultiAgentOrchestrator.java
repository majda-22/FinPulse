package net.omaima.services;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import net.omaima.agent.*;
import net.omaima.entities.ChatSession;
import net.omaima.entities.User;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
@Slf4j
@RequiredArgsConstructor
public class MultiAgentOrchestrator {

    private final IngestionPipelineService ingestionPipelineService;
    private final ChatSessionService chatSessionService;
    private final ChatClient chatClient;
    private final Agent1SupportExtractor agent1;
    private final Agent2RedFlagsExtractor agent2;
    private final Agent3FinalSynthesizer agent3;
    private final Agent4PdfAssembly agent4;
    private final Agent5MarketNews agent5;

    // =====================================================================
    // POINT D'ENTRÉE UNIQUE
    // =====================================================================

    @Transactional
    public OrchestratorResult handleMessage(User user, String ticker, String userMessage) {
        log.info("=== ORCHESTRATOR === user={} ticker={}", user.getUsername(), ticker);

        // Ticker manquant → demande de clarification immédiate
        if (ticker == null || ticker.isBlank()) {
            return OrchestratorResult.clarification(
                    "Pour vous aider, j'ai besoin du ticker de l'entreprise (ex: AAPL, TSLA, MSFT). " +
                            "Quelle entreprise souhaitez-vous analyser ?"
            );
        }

        // Entreprise inconnue → backfill
        if (!checkIfCompanyExists(ticker)) {
            ingestionPipelineService.triggerBackfillPipeline(ticker);
            return OrchestratorResult.clarification(
                    "L'entreprise " + ticker + " n'est pas encore dans notre base. " +
                            "Son ingestion est lancée. Veuillez réessayer dans quelques instants."
            );
        }

        // Détection d'intention via LLM
        IntentResult intent = detectIntentWithLLM(userMessage, ticker);
        log.info("Intent: {}", intent.mode());

        return switch (intent.mode()) {
            case OUT_OF_SCOPE -> OrchestratorResult.clarification(
                    "Je suis un assistant financier spécialisé. " +
                            "Posez-moi une question sur " + ticker + " ou une entreprise cotée."
            );
            case NEEDS_CLARIFICATION -> OrchestratorResult.clarification(intent.clarificationQuestion());
            case REPORT -> OrchestratorResult.reportGenerated(
                    generateStrategyReport(user, ticker, userMessage)
            );
            default -> OrchestratorResult.chatResponse(handleChatbot(user, ticker, userMessage));
        };
    }

    // =====================================================================
    // DÉTECTION D'INTENTION VIA LLM
    // =====================================================================

    private IntentResult detectIntentWithLLM(String message, String ticker) {
        try {
            String prompt = String.format("""
                Tu es le routeur intelligent d'un assistant financier FinPulse.
                
                TICKER: %s
                MESSAGE: "%s"
                
                Classifie en:
                - CHATBOT : question factuelle sur l'entreprise
                - REPORT  : demande d'analyse stratégique avec un argument d'investissement clair
                - OUT_OF_SCOPE : sans rapport avec la finance
                - NEEDS_CLARIFICATION : veut un rapport mais argument trop vague ou absent
                
                Si NEEDS_CLARIFICATION, formule une question pour guider l'utilisateur
                vers un argument d'investissement précis.
                
                Réponds UNIQUEMENT en JSON:
                {
                  "mode": "CHATBOT|REPORT|OUT_OF_SCOPE|NEEDS_CLARIFICATION",
                  "clarification_question": "... ou null"
                }
                """, ticker, message);

            String response = chatClient.prompt().user(prompt).call().content();
            int start = response.indexOf("{");
            int end   = response.lastIndexOf("}") + 1;

            if (start >= 0 && end > start) {
                var mapper = new com.fasterxml.jackson.databind.ObjectMapper();
                var node   = mapper.readTree(response.substring(start, end));
                String modeStr = node.get("mode").asText("CHATBOT");
                String clarif  = node.has("clarification_question")
                        && !node.get("clarification_question").isNull()
                        ? node.get("clarification_question").asText() : null;

                Mode mode = switch (modeStr) {
                    case "REPORT"              -> Mode.REPORT;
                    case "OUT_OF_SCOPE"        -> Mode.OUT_OF_SCOPE;
                    case "NEEDS_CLARIFICATION" -> Mode.NEEDS_CLARIFICATION;
                    default                    -> Mode.CHATBOT;
                };
                return new IntentResult(mode, clarif);
            }
        } catch (Exception e) {
            log.error("Erreur détection intent → fallback CHATBOT", e);
        }
        return new IntentResult(Mode.CHATBOT, null);
    }

    // =====================================================================
    // MODE 1 : CHATBOT
    // =====================================================================

    @Transactional
    public String handleChatbot(User user, String ticker, String userMessage) {
        log.info("=== MODE CHATBOT ===");
        ChatSession session = chatSessionService.createSession(user, ticker, "AGENT");
        try {
            String companyName   = ingestionPipelineService.getCompanyName(ticker);
            Double nciGlobal     = ingestionPipelineService.getNciGlobal(ticker);
            String embeddingText = ingestionPipelineService.getLatestEmbeddingText(ticker, 0);
            String filedAt       = ingestionPipelineService.getLatestEmbeddingFiledAt(ticker);
            Double priceClose    = ingestionPipelineService.getPriceClose(ticker);

            String secContext = String.format(
                    "Entreprise: %s (%s)\nNCI Global: %.2f\nRapport SEC: %s\nPrix: $%.2f\n\n%s",
                    companyName, ticker, nciGlobal, filedAt, priceClose, embeddingText);

            String aiResponse = chatClient.prompt()
                    .user(u -> u.text("""
                    Tu es un assistant financier expert et factuel pour FinPulse.
                    
                    RÈGLES ABSOLUES:
                    - Réponds UNIQUEMENT à partir des données SEC fournies
                    - Si l'info est absente: "Cette information n'est pas disponible dans le rapport SEC."
                    - Ne jamais inventer de chiffres, dates ou faits
                    - Hors sujet financier: "Je suis spécialisé en analyse financière."
                    - Cite ta source: "Selon le rapport SEC du {filedAt}"
                    - Sois concis, professionnel, factuel
                    
                    CONTEXTE SEC:
                    {context}
                    
                    QUESTION: {question}
                    """)
                            .arg("filedAt", filedAt)
                            .arg("context", secContext)
                            .arg("question", userMessage))
                    .call().content();

            chatSessionService.saveMessage(session, "USER", userMessage,
                    chatSessionService.detectIntent(userMessage), nciGlobal);
            chatSessionService.saveMessage(session, "AI", aiResponse, "RESPONSE", nciGlobal);
            return aiResponse;

        } catch (Exception e) {
            log.error("Erreur chatbot", e);
            return "Une erreur s'est produite. Veuillez réessayer.";
        }
    }

    // =====================================================================
    // MODE 2 : GÉNÉRATION RAPPORT — SANS sauvegarde automatique
    // =====================================================================

    /**
     * Génère le rapport et retourne toutes les données calculées.
     * La sauvegarde en base N'EST PAS faite ici.
     * Elle sera faite UNIQUEMENT si l'utilisateur clique sur
     * "Enregistrer la stratégie" → POST /api/v2/strategy/save
     */
    public ReportResult generateStrategyReport(User user, String ticker, String userArgument) {
        log.info("=== MODE RAPPORT (génération sans sauvegarde) ===");
        try {
            String companyName   = ingestionPipelineService.getCompanyName(ticker);
            Double nciGlobal     = ingestionPipelineService.getNciGlobal(ticker);
            String embeddingText = ingestionPipelineService.getLatestEmbeddingText(ticker, 0);
            Double priceClose    = ingestionPipelineService.getPriceClose(ticker);
            Double sentiment     = ingestionPipelineService.getSentimentScore(ticker);

            List<String> news = agent5.getRecentNews(ticker);
            if (news.isEmpty()) news = List.of("Aucune actualité disponible pour " + ticker);

            log.info("Phase 1: Agent1...");
            List<String> supportPoints = agent1.extractSupportEvidence(
                    userArgument, embeddingText, companyName);

            log.info("Phase 2: Agent2...");
            Agent2RedFlagsExtractor.RiskAnalysisResult risk =
                    agent2.analyzeRedFlags(userArgument, embeddingText, nciGlobal);

            log.info("Phase 3: Agent3...");
            String finalConclusion = agent3.synthesizeFinalConclusion(
                    userArgument, supportPoints, risk.redFlags(),
                    risk.fConsistency(), sentiment, priceClose, news);

            log.info("Agent4: PDF...");
            byte[] pdfBytes = agent4.generateStrategyReport(
                    ticker, companyName, userArgument,
                    supportPoints, risk.redFlags(),
                    risk.fConsistency(), nciGlobal, risk.nciPersonalized(),
                    sentiment, finalConclusion);

            log.info("✅ Rapport généré ({} bytes) — sauvegarde en attente du choix utilisateur", pdfBytes.length);

            return new ReportResult(
                    pdfBytes, ticker, companyName, userArgument,
                    nciGlobal, risk.nciPersonalized(), risk.fConsistency(),
                    sentiment, supportPoints.toString(), risk.redFlags().toString(), finalConclusion
            );

        } catch (Exception e) {
            log.error("Erreur génération rapport", e);
            throw new RuntimeException("Échec génération rapport", e);
        }
    }

    // =====================================================================
    // UTILITAIRES
    // =====================================================================

    public boolean checkIfCompanyExists(String ticker) {
        try {
            ingestionPipelineService.getCompanyName(ticker);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    // =====================================================================
    // TYPES
    // =====================================================================

    public enum Mode { CHATBOT, REPORT, OUT_OF_SCOPE, NEEDS_CLARIFICATION }

    public record IntentResult(Mode mode, String clarificationQuestion) {}

    /**
     * Toutes les données calculées lors de la génération du rapport.
     * Retournées au frontend pour affichage ET pour la sauvegarde optionnelle.
     */
    public record ReportResult(
            byte[]  pdfBytes,
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

    public record OrchestratorResult(
            Mode         mode,
            String       textResponse,
            ReportResult reportResult
    ) {
        public static OrchestratorResult chatResponse(String text) {
            return new OrchestratorResult(Mode.CHATBOT, text, null);
        }
        public static OrchestratorResult clarification(String question) {
            return new OrchestratorResult(Mode.NEEDS_CLARIFICATION, question, null);
        }
        public static OrchestratorResult reportGenerated(ReportResult r) {
            return new OrchestratorResult(Mode.REPORT, null, r);
        }
    }
}