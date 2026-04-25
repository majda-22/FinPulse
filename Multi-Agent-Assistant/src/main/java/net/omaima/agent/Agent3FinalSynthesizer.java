package net.omaima.agent;


import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.stereotype.Service;
import java.util.List;

@Service
@Slf4j
@RequiredArgsConstructor
public class Agent3FinalSynthesizer {

    private final ChatClient chatClient;

    public String synthesizeFinalConclusion(
            String userIdea,
            List<String> supportPoints,
            List<String> redFlags,
            Double fConsistency,
            Double marketSentiment,
            Double marketPrice,
            List<String> newsHeadlines) {

        log.info("Agent 3: Synthesizing final conclusion");

        try {
            String supportText = String.join("\n- ", supportPoints);
            String redFlagsText = String.join("\n- ", redFlags);
            String newsText = String.join("\n- ", newsHeadlines);

            String prompt = String.format("""
                Vous êtes un analyste financier senior. Synthétisez cette analyse en 3-4 paragraphes professionnels:
                
                IDÉE: %s
                
                PHASE 1 - PREUVES POSITIVES:
                - %s
                
                PHASE 2 - RISQUES IDENTIFIÉS:
                - %s
                
                SCORE DE CONTRADICTION (F_Consistency): %.2f
                Interprétation:
                - < 0.3: Très faible contradiction - l'idée semble valide
                - < 0.6: Contradiction modérée - l'idée a des mérites mais aussi des risques
                - >= 0.6: Forte contradiction - l'idée est fortement contredite
                
                DONNÉES DE MARCHÉ:
                - Sentiment: %.2f
                - Prix: $%.2f
                - Actualités: %s
                
                Fournissez une conclusion professionnelle couvrant:
                1. Résumé et contexte
                2. Validité de l'idée
                3. Opportunités
                4. Menaces
                5. Recommandation finale
                """,
                    userIdea, supportText, redFlagsText, fConsistency,
                    marketSentiment, marketPrice, newsText);

            String conclusion = chatClient.prompt()
                    .user(prompt)
                    .call()
                    .content();

            log.info("Conclusion synthesized successfully");
            return conclusion;
        } catch (Exception e) {
            log.error("Error synthesizing conclusion", e);
            throw new RuntimeException("Failed to synthesize conclusion", e);
        }
    }
}
