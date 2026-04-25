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
public class Agent1SupportExtractor {

    private final ChatClient chatClient;
    private final ObjectMapper objectMapper;

    public List<String> extractSupportEvidence(String userIdea, String secText, String companyName) {
        log.info("Agent 1: Extracting support evidence");

        try {
            String prompt = String.format("""
                Vous êtes un analyste financier expert. Extraire uniquement les points POSITIFS du texte SEC qui soutiennent cette idée:
                
                Idée: %s
                Entreprise: %s
                
                Texte SEC:
                %s
                
                Cherche uniquement les points POSITIFS. Retourne JSON:
                {
                  "support_points": ["Point 1", "Point 2", ...]
                }
                """, userIdea, companyName, secText);

            String response = chatClient.prompt()
                    .user(prompt)
                    .call()
                    .content();

            // Parse JSON from response
            int startIdx = response.indexOf("{");
            int endIdx = response.lastIndexOf("}") + 1;
            if (startIdx >= 0 && endIdx > startIdx) {
                String jsonStr = response.substring(startIdx, endIdx);
                JsonNode node = objectMapper.readTree(jsonStr);

                List<String> points = new ArrayList<>();
                for (JsonNode point : node.get("support_points")) {
                    points.add(point.asText());
                }

                log.info("Found {} support points", points.size());
                return points;
            }

            return new ArrayList<>();
        } catch (Exception e) {
            log.error("Error extracting support evidence", e);
            throw new RuntimeException("Failed to extract support evidence", e);
        }
    }
}
