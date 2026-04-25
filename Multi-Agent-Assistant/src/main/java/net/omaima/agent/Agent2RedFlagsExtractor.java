package net.omaima.agent;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.stereotype.Service;
import java.util.ArrayList;
import java.util.List;

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
        log.info("Agent 2: Analyzing red flags and calculating F_Consistency");

        try {
            String prompt = String.format("""
                Vous êtes un analyste de risque. Extraire les risques (Item 1A) qui contredisent cette idée:
                
                Idée: %s
                Score NCI Global: %.2f
                
                Texte SEC:
                %s
                
                Calculer F_Consistency (0=pas de contradiction, 1=contradiction totale).
                Formule: NCI_Personnalisé = %.2f + (F_Consistency × 20)
                
                Retourne JSON:
                {
                  "red_flags": ["Risque 1", "Risque 2", ...],
                  "f_consistency": 0.X,
                  "nci_personalized": Y.Y,
                  "analysis_summary": "Résumé"
                }
                """, userIdea, nciGlobal, secText, nciGlobal);

            String response = chatClient.prompt()
                    .user(prompt)
                    .call()
                    .content();

            int startIdx = response.indexOf("{");
            int endIdx = response.lastIndexOf("}") + 1;
            if (startIdx >= 0 && endIdx > startIdx) {
                String jsonStr = response.substring(startIdx, endIdx);
                JsonNode node = objectMapper.readTree(jsonStr);

                List<String> redFlags = new ArrayList<>();
                for (JsonNode flag : node.get("red_flags")) {
                    redFlags.add(flag.asText());
                }

                Double fConsistency = node.get("f_consistency").asDouble();
                Double nciPersonalized = node.get("nci_personalized").asDouble();
                String summary = node.get("analysis_summary").asText();

                log.info("Red flags analysis: {} flags, F_consistency={}",
                        redFlags.size(), fConsistency);

                return new RiskAnalysisResult(redFlags, fConsistency, nciPersonalized, summary);
            }

            return new RiskAnalysisResult(new ArrayList<>(), 0.0, nciGlobal, "");
        } catch (Exception e) {
            log.error("Error analyzing red flags", e);
            throw new RuntimeException("Failed to analyze red flags", e);
        }
    }
}
