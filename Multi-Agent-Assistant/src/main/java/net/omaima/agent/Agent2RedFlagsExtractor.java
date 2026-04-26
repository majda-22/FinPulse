package net.omaima.agent;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

/**
 *
 * Rôle : extraire les risques du rapport SEC (Item 1A) qui contredisent
 * l'argument, et calculer F_Consistency + NCI personnalisé.
 *
 * Corrections apportées :
 * - Prompt plus strict : bornes explicites pour f_consistency (0.0 à 1.0)
 * - Validation des valeurs numériques en sortie
 * - Interdiction d'inventer des risques non présents dans le SEC
 */
@Service
@Slf4j
@RequiredArgsConstructor
public class Agent2RedFlagsExtractor {

    private final ChatClient chatClient;
    private final ObjectMapper objectMapper;

    public record RiskAnalysisResult(
            List<String> redFlags,
            Double fConsistency,
            Double nciPersonalized,
            String analysisSummary
    ) {}

    public RiskAnalysisResult analyzeRedFlags(String userIdea, String secText, Double nciGlobal) {
        log.info("Agent2 (RedFlagsExtractor): Analyse des risques, NCI Global={}", nciGlobal);

        try {
            String prompt = String.format("""
                Tu es un analyste de risque financier senior. Ta mission est d'identifier
                dans le texte SEC les facteurs de risque qui CONTREDISENT l'argument suivant.
 
                ARGUMENT DE L'UTILISATEUR: %s
                SCORE NCI GLOBAL DE RÉFÉRENCE: %.2f
 
                TEXTE SEC (source officielle):
                %s
 
                RÈGLES STRICTES:
                - Extrait UNIQUEMENT des risques présents dans le texte SEC ci-dessus (Item 1A ou équivalent)
                - NE PAS inventer de risques absents du document
                - Maximum 5 red flags, chacun factuel et sourcé
                - f_consistency DOIT être un nombre entre 0.0 et 1.0:
                    * 0.0 à 0.3 : peu de contradiction, l'idée tient la route
                    * 0.3 à 0.6 : contradiction modérée
                    * 0.6 à 1.0 : forte contradiction, l'idée est risquée
                - Formule NCI personnalisé: nci_personalized = %.2f + (f_consistency × 20)
                  (Un NCI plus élevé = moins fiable pour cet argument spécifique)
                - analysis_summary : 2-3 phrases résumant l'analyse de risque
 
                Réponds UNIQUEMENT en JSON valide, sans texte avant ou après:
                {
                  "red_flags": ["Risque factuel 1", "Risque factuel 2"],
                  "f_consistency": 0.X,
                  "nci_personalized": Y.Y,
                  "analysis_summary": "Résumé factuel de l'analyse"
                }
                """, userIdea, nciGlobal, truncateText(secText, 4000), nciGlobal);

            String response = chatClient.prompt()
                    .user(prompt)
                    .call()
                    .content();

            return parseResult(response, nciGlobal);

        } catch (Exception e) {
            log.error("Erreur Agent2 RedFlagsExtractor", e);
            throw new RuntimeException("Échec analyse red flags", e);
        }
    }

    private RiskAnalysisResult parseResult(String response, Double nciGlobal) {
        try {
            int startIdx = response.indexOf("{");
            int endIdx = response.lastIndexOf("}") + 1;

            if (startIdx >= 0 && endIdx > startIdx) {
                String jsonStr = response.substring(startIdx, endIdx);
                JsonNode node = objectMapper.readTree(jsonStr);

                List<String> redFlags = new ArrayList<>();
                if (node.has("red_flags")) {
                    for (JsonNode flag : node.get("red_flags")) {
                        redFlags.add(flag.asText());
                    }
                }

                // ✅ Validation des valeurs numériques
                double fConsistency = node.has("f_consistency")
                        ? clamp(node.get("f_consistency").asDouble(), 0.0, 1.0)
                        : 0.0;

                double nciPersonalized = node.has("nci_personalized")
                        ? node.get("nci_personalized").asDouble()
                        : nciGlobal + (fConsistency * 20);

                String summary = node.has("analysis_summary")
                        ? node.get("analysis_summary").asText()
                        : "";

                log.info("Agent2: {} red flags, f_consistency={}, nci_personalized={}",
                        redFlags.size(), fConsistency, nciPersonalized);

                return new RiskAnalysisResult(redFlags, fConsistency, nciPersonalized, summary);
            }
        } catch (Exception e) {
            log.error("Erreur parsing JSON Agent2", e);
        }
        // Fallback safe
        return new RiskAnalysisResult(new ArrayList<>(), 0.0, nciGlobal, "Analyse indisponible");
    }

    private double clamp(double value, double min, double max) {
        return Math.max(min, Math.min(max, value));
    }

    private String truncateText(String text, int maxChars) {
        if (text == null) return "";
        return text.length() > maxChars ? text.substring(0, maxChars) + "..." : text;
    }
}