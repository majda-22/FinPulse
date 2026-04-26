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
 * Rôle : extraire du rapport SEC les points factuels qui SOUTIENNENT
 * l'argument d'investissement de l'utilisateur.
 *
 * Corrections apportées :
 * - Prompt plus strict : interdit les inventions
 * - Limite à 5 points maximum pour rester factuel
 * - Demande la citation de la source SEC exacte
 */
@Service
@Slf4j
@RequiredArgsConstructor
public class Agent1SupportExtractor {

    private final ChatClient chatClient;
    private final ObjectMapper objectMapper;

    public List<String> extractSupportEvidence(String userIdea, String secText, String companyName) {
        log.info("Agent1 (SupportExtractor): Extraction des preuves de soutien pour '{}'", companyName);

        try {
            String prompt = String.format("""
                Tu es un analyste financier senior. Ta mission est d'extraire du texte SEC
                les éléments FACTUELS qui soutiennent l'argument d'investissement suivant.
 
                ARGUMENT DE L'UTILISATEUR: %s
                ENTREPRISE: %s
 
                TEXTE SEC (source officielle):
                %s
 
                RÈGLES STRICTES:
                - Extrait UNIQUEMENT des faits présents dans le texte SEC ci-dessus
                - NE PAS inventer, extrapoler ou supposer
                - Si aucun élément ne soutient l'argument, retourne une liste vide
                - Maximum 5 points, chacun avec une citation courte du texte source
                - Chaque point doit être une phrase complète et factuelle
 
                Réponds UNIQUEMENT en JSON valide, sans texte avant ou après:
                {
                  "support_points": [
                    "Point factuel 1 (source: extrait du SEC)",
                    "Point factuel 2 (source: extrait du SEC)"
                  ]
                }
                """, userIdea, companyName, truncateText(secText, 4000));

            String response = chatClient.prompt()
                    .user(prompt)
                    .call()
                    .content();

            return parseStringList(response, "support_points");

        } catch (Exception e) {
            log.error("Erreur Agent1 SupportExtractor", e);
            throw new RuntimeException("Échec extraction preuves de soutien", e);
        }
    }

    private List<String> parseStringList(String response, String key) throws Exception {
        int startIdx = response.indexOf("{");
        int endIdx = response.lastIndexOf("}") + 1;
        if (startIdx >= 0 && endIdx > startIdx) {
            String jsonStr = response.substring(startIdx, endIdx);
            JsonNode node = objectMapper.readTree(jsonStr);
            List<String> result = new ArrayList<>();
            if (node.has(key)) {
                for (JsonNode item : node.get(key)) {
                    result.add(item.asText());
                }
            }
            log.info("Agent1: {} points extraits", result.size());
            return result;
        }
        return new ArrayList<>();
    }

    /** Évite de dépasser la fenêtre de contexte du LLM */
    private String truncateText(String text, int maxChars) {
        if (text == null) return "";
        return text.length() > maxChars ? text.substring(0, maxChars) + "..." : text;
    }
}
