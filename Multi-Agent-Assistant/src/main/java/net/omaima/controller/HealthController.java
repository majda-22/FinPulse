package net.omaima.controller;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import net.omaima.services.IngestionPipelineService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;

@RestController
@RequiredArgsConstructor
@Slf4j
public class HealthController {

    private final IngestionPipelineService ingestionPipelineService;

    record HealthResponse(String status, LocalDateTime timestamp, String service) {}
    record StatusResponse(String status, LocalDateTime timestamp, Map<String, String> components, String version) {}

    @GetMapping("/health")
    public ResponseEntity<HealthResponse> health() {
        log.info("Health check requested");
        return ResponseEntity.ok(new HealthResponse(
                "UP", LocalDateTime.now(), "FinPulse Assistant P2 - Multi-Agent System"));
    }

    @GetMapping("/status")
    public ResponseEntity<StatusResponse> status() {
        log.info("Status check requested");

        boolean p1Available = checkP1Api();

        Map<String, String> components = new HashMap<>();
        components.put("Core API", "UP");
        components.put("P1 Backend", p1Available ? "UP" : "DOWN");
        components.put("Database", "UP");
        components.put("Redis Cache", "UP");
        components.put("LLM Service", "UP");

        String overallStatus = p1Available ? "HEALTHY" : "DEGRADED";

        return ResponseEntity.ok(new StatusResponse(
                overallStatus, LocalDateTime.now(), components, "v1.0.0"));
    }

    private boolean checkP1Api() {
        try {
            ingestionPipelineService.getCompanyName("AAPL");
            return true;
        } catch (Exception e) {
            log.warn("P1 API unavailable: {}", e.getMessage());
            return false;
        }
    }
}