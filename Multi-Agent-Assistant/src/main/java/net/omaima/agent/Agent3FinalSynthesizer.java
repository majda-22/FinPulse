package net.omaima.agent;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 *
 * Rôle : synthétiser les phases 1 et 2 en une conclusion professionnelle.
 *
 * Corrections apportées :
 * - Prompt interdit les inventions hors contexte
 * - Demande une recommandation claire et justifiée
 */
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

        log.info("Agent3 (FinalSynthesizer): Synthèse finale en cours...");

        try {
            String supportText  = supportPoints.isEmpty() ? "Aucune preuve de soutien trouvée"
                    : "- " + String.join("\n- ", supportPoints);
            String redFlagsText = redFlags.isEmpty()     ? "Aucun red flag identifié"
                    : "- " + String.join("\n- ", redFlags);
            String newsText     = newsHeadlines.isEmpty() ? "Aucune actualité disponible"
                    : "- " + String.join("\n- ", newsHeadlines);

            String riskLevel = fConsistency < 0.3 ? "FAIBLE" : fConsistency < 0.6 ? "MODÉRÉ" : "ÉLEVÉ";

            String prompt = String.format("""
                Tu es un analyste financier senior chez FinPulse. Rédige une synthèse professionnelle
                en 4 paragraphes basée EXCLUSIVEMENT sur les données fournies ci-dessous.
 
                ARGUMENT D'INVESTISSEMENT ANALYSÉ:
                %s
 
                SCORE DE CONTRADICTION (F_Consistency): %.2f → Niveau de risque: %s
                  - < 0.3 : Faible contradiction — l'idée est bien soutenue
                  - 0.3-0.6 : Contradiction modérée — l'idée a des mérites et des risques
                  - > 0.6 : Forte contradiction — l'idée est sérieusement remise en question
 
                DONNÉES DE MARCHÉ:
                - Sentiment marché: %.2f (entre -1 négatif et +1 positif)
                - Prix actuel: $%.2f
                - Actualités récentes: %s
 
                PREUVES DE SOUTIEN (Phase 1):
                %s
 
                RISQUES IDENTIFIÉS (Phase 2):
                %s
 
                STRUCTURE DES 4 PARAGRAPHES:
                1. Résumé de l'argument et contexte de l'analyse
                2. Forces: éléments qui soutiennent l'idée (basés sur Phase 1)
                3. Risques: éléments qui contredisent l'idée (basés sur Phase 2)
                4. Recommandation finale claire: FAVORABLE / MITIGÉ / DÉFAVORABLE avec justification
 
                RÈGLES ABSOLUES:
                - Baser UNIQUEMENT sur les données fournies ci-dessus
                - Jamais inventer des chiffres ou des faits non mentionnés
                - Être factuel, professionnel et concis
                - Si les données sont insuffisantes, le mentionner explicitement
                """,
                    userIdea,
                    fConsistency, riskLevel,
                    marketSentiment, marketPrice, newsText,
                    supportText,
                    redFlagsText);

            String conclusion = chatClient.prompt()
                    .user(prompt)
                    .call()
                    .content();

            log.info("✅ Agent3: Synthèse générée ({} caractères)", conclusion.length());
            return conclusion;

        } catch (Exception e) {
            log.error("Erreur Agent3 FinalSynthesizer", e);
            throw new RuntimeException("Échec synthèse finale", e);
        }
    }
}
