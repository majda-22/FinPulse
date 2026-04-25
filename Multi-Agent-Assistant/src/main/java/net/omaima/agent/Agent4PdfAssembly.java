package net.omaima.agent;

import com.itextpdf.kernel.pdf.PdfWriter;
import com.itextpdf.layout.Document;
import com.itextpdf.layout.element.Paragraph;
import com.itextpdf.layout.element.Table;
import com.itextpdf.layout.element.Cell;
import com.itextpdf.layout.properties.TextAlignment;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import java.io.ByteArrayOutputStream;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;

@Service
@Slf4j
@RequiredArgsConstructor
public class Agent4PdfAssembly {

    private static final DateTimeFormatter DATE_FORMAT = DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm");

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

        log.info("Agent 4: Generating PDF report for {}", ticker);

        try {
            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            PdfWriter writer = new PdfWriter(baos);
            com.itextpdf.kernel.pdf.PdfDocument pdfDoc = new com.itextpdf.kernel.pdf.PdfDocument(writer);
            Document document = new Document(pdfDoc);

            // HEADER
            Paragraph title = new Paragraph("RAPPORT D'ANALYSE STRATÉGIQUE")
                    .setFontSize(24)
                    .setBold()
                    .setTextAlignment(TextAlignment.CENTER);
            document.add(title);

            Paragraph subtitle = new Paragraph(companyName + " (" + ticker + ")")
                    .setFontSize(16)
                    .setTextAlignment(TextAlignment.CENTER);
            document.add(subtitle);

            Paragraph date = new Paragraph("Généré le " + LocalDateTime.now().format(DATE_FORMAT))
                    .setFontSize(10)
                    .setTextAlignment(TextAlignment.CENTER);
            document.add(date);

            document.add(new Paragraph("\n"));

            // EXECUTIVE SUMMARY
            document.add(new Paragraph("RÉSUMÉ EXÉCUTIF").setFontSize(14).setBold());
            document.add(new Paragraph("Idée: " + userIdea));

            // Score table
            Table scoreTable = new Table(2);
            scoreTable.addCell(new Cell().add(new Paragraph("NCI Global").setBold()));
            scoreTable.addCell(new Cell().add(new Paragraph(String.format("%.2f", nciGlobal))));
            scoreTable.addCell(new Cell().add(new Paragraph("NCI Personnalisé").setBold()));
            scoreTable.addCell(new Cell().add(new Paragraph(String.format("%.2f", nciPersonalized))));
            scoreTable.addCell(new Cell().add(new Paragraph("F_Consistency").setBold()));
            scoreTable.addCell(new Cell().add(new Paragraph(String.format("%.2f", fConsistency))));
            scoreTable.addCell(new Cell().add(new Paragraph("Sentiment Marché").setBold()));
            scoreTable.addCell(new Cell().add(new Paragraph(String.format("%.2f", marketSentiment))));
            document.add(scoreTable);
            document.add(new Paragraph("\n"));

            // PHASE 1
            document.add(new Paragraph("PHASE 1: PREUVES DE SOUTIEN").setFontSize(12).setBold());
            for (String point : supportPoints) {
                document.add(new Paragraph("✓ " + point).setMarginLeft(20));
            }
            document.add(new Paragraph("\n"));

            // PHASE 2
            document.add(new Paragraph("PHASE 2: RED FLAGS (RISQUES)").setFontSize(12).setBold());
            for (String flag : redFlags) {
                document.add(new Paragraph("⚠ " + flag).setMarginLeft(20));
            }
            document.add(new Paragraph("\n"));

            // PHASE 3
            document.add(new Paragraph("PHASE 3: ANALYSE ET CONCLUSION").setFontSize(12).setBold());
            document.add(new Paragraph(finalConclusion));

            // FOOTER
            document.add(new Paragraph("\n"));
            Paragraph footer = new Paragraph("Rapport généré automatiquement par FinPulse Assistant")
                    .setFontSize(8)
                    .setTextAlignment(TextAlignment.CENTER);
            document.add(footer);

            document.close();

            log.info("PDF generated successfully. Size: {} bytes", baos.size());
            return baos.toByteArray();

        } catch (Exception e) {
            log.error("Error generating PDF", e);
            throw new RuntimeException("Failed to generate PDF", e);
        }
    }
}