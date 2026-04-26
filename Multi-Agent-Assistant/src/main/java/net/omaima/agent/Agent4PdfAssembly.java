package net.omaima.agent;

import com.itextpdf.kernel.pdf.PdfWriter;
import com.itextpdf.layout.Document;
import com.itextpdf.layout.element.Paragraph;
import com.itextpdf.layout.element.Table;
import com.itextpdf.layout.element.Cell;
import com.itextpdf.layout.properties.TextAlignment;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.io.ByteArrayOutputStream;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;

/**
 * ✅ Renommé : Agent9PdfAssembly → Agent4PdfAssembly
 * Pas de LLM — uniquement iText7 pour générer le PDF.
 */
@Service
@Slf4j
public class Agent4PdfAssembly {

    private static final DateTimeFormatter DATE_FORMAT =
            DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm");

    public byte[] generateStrategyReport(
            String ticker,
            String companyName,
            String userIdea,
            List<String> supportPoints,
            List<String> redFlags,
            Double fConsistency,
            Double nciGlobal,
            Double nciPersonalized,
            Double marketSentiment,
            String finalConclusion) {

        log.info("Agent4 (PdfAssembly): Génération PDF pour {}", ticker);

        try {
            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            PdfWriter writer = new PdfWriter(baos);
            com.itextpdf.kernel.pdf.PdfDocument pdfDoc =
                    new com.itextpdf.kernel.pdf.PdfDocument(writer);
            Document document = new Document(pdfDoc);

            // En-tête
            document.add(new Paragraph("RAPPORT D'ANALYSE STRATÉGIQUE")
                    .setFontSize(22).setBold().setTextAlignment(TextAlignment.CENTER));
            document.add(new Paragraph(companyName + " (" + ticker + ")")
                    .setFontSize(16).setTextAlignment(TextAlignment.CENTER));
            document.add(new Paragraph("Généré le " + LocalDateTime.now().format(DATE_FORMAT))
                    .setFontSize(10).setTextAlignment(TextAlignment.CENTER));
            document.add(new Paragraph("\n"));

            // Argument
            document.add(new Paragraph("ARGUMENT ANALYSÉ").setFontSize(13).setBold());
            document.add(new Paragraph(userIdea));
            document.add(new Paragraph("\n"));

            // Scores
            document.add(new Paragraph("SCORES DE L'ANALYSE").setFontSize(13).setBold());
            Table scoreTable = new Table(2);
            scoreTable.addCell(new Cell().add(new Paragraph("NCI Global").setBold()));
            scoreTable.addCell(new Cell().add(new Paragraph(String.format("%.2f", nciGlobal))));
            scoreTable.addCell(new Cell().add(new Paragraph("NCI Personnalisé").setBold()));
            scoreTable.addCell(new Cell().add(new Paragraph(String.format("%.2f", nciPersonalized))));
            scoreTable.addCell(new Cell().add(new Paragraph("F_Consistency").setBold()));
            scoreTable.addCell(new Cell().add(new Paragraph(String.format("%.2f", fConsistency)
                    + interpretFConsistency(fConsistency))));
            scoreTable.addCell(new Cell().add(new Paragraph("Sentiment marché").setBold()));
            scoreTable.addCell(new Cell().add(new Paragraph(String.format("%.2f", marketSentiment))));
            document.add(scoreTable);
            document.add(new Paragraph("\n"));

            // Phase 1
            document.add(new Paragraph("PHASE 1 — PREUVES DE SOUTIEN").setFontSize(12).setBold());
            if (supportPoints.isEmpty()) {
                document.add(new Paragraph("Aucune preuve de soutien identifiée dans le rapport SEC.")
                        .setItalic());
            } else {
                for (String point : supportPoints) {
                    document.add(new Paragraph("✓ " + point).setMarginLeft(20));
                }
            }
            document.add(new Paragraph("\n"));

            // Phase 2
            document.add(new Paragraph("PHASE 2 — RED FLAGS (RISQUES)").setFontSize(12).setBold());
            if (redFlags.isEmpty()) {
                document.add(new Paragraph("Aucun red flag majeur identifié dans le rapport SEC.")
                        .setItalic());
            } else {
                for (String flag : redFlags) {
                    document.add(new Paragraph("⚠ " + flag).setMarginLeft(20));
                }
            }
            document.add(new Paragraph("\n"));

            // Phase 3 — Conclusion
            document.add(new Paragraph("PHASE 3 — SYNTHÈSE ET RECOMMANDATION").setFontSize(12).setBold());
            document.add(new Paragraph(finalConclusion));

            // Footer
            document.add(new Paragraph("\n"));
            document.add(new Paragraph(
                    "Rapport généré automatiquement par FinPulse Assistant — Usage interne uniquement")
                    .setFontSize(8).setTextAlignment(TextAlignment.CENTER).setItalic());

            document.close();

            log.info("✅ Agent4: PDF généré ({} bytes)", baos.size());
            return baos.toByteArray();

        } catch (Exception e) {
            log.error("Erreur Agent4 PdfAssembly", e);
            throw new RuntimeException("Échec génération PDF", e);
        }
    }

    private String interpretFConsistency(double f) {
        if (f < 0.3) return " (risque FAIBLE)";
        if (f < 0.6) return " (risque MODÉRÉ)";
        return " (risque ÉLEVÉ)";
    }
}