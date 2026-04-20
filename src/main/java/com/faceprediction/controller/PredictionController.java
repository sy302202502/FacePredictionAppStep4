package com.faceprediction.controller;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

import com.faceprediction.entity.PredictionResult;
import com.faceprediction.service.PredictionService;

@Controller
@RequestMapping("/prediction")
public class PredictionController {

    private final PredictionService predictionService;

    @Value("${upload.dir}")
    private String uploadDir;

    @Value("${python.script.dir}")
    private String pythonScriptDir;

    @Autowired
    public PredictionController(PredictionService predictionService) {
        this.predictionService = predictionService;
    }

    // /prediction → /predict-v2 にリダイレクト（旧URL対策）
    @GetMapping
    public String redirectToPredictV2() {
        return "redirect:/predict-v2";
    }

    // /prediction/run GET → /script にリダイレクト（旧URL対策）
    @GetMapping("/run")
    public String redirectToScript() {
        return "redirect:/script";
    }

    // /prediction/run POST → /script にリダイレクト（旧URL対策）
    @PostMapping("/run")
    public String redirectToScriptPost() {
        return "redirect:/script";
    }

    // 勝ち馬顔特徴の統計ページ（差分分析・レース種別フィルタ対応）
    @GetMapping("/stats")
    public String showStats(
            @RequestParam(required = false, defaultValue = "") String category,
            Model model) {
        String cat = category.isBlank() ? null : category;
        Map<String, Map<String, Map<String, Double>>> diffStats = predictionService.buildDiffStats(cat);
        long winnerCount = predictionService.getAnalyzedWinnerCount();
        long loserCount = predictionService.getAnalyzedLoserCount();
        model.addAttribute("diffStats", diffStats);
        model.addAttribute("winnerCount", winnerCount);
        model.addAttribute("loserCount", loserCount);
        model.addAttribute("categoryLabels", predictionService.getCategoryLabels());
        model.addAttribute("selectedCategory", category);
        return "prediction/stats";
    }

    // PDF 出力（/prediction/pdf?raceName=xxx）
    @GetMapping("/pdf")
    @ResponseBody
    public ResponseEntity<byte[]> exportPdf(
            @RequestParam(required = false) String raceName) {

        if (raceName == null || raceName.isBlank()) {
            return ResponseEntity.badRequest()
                    .body("raceName パラメータが必要です".getBytes(StandardCharsets.UTF_8));
        }

        String scriptPath = pythonScriptDir + File.separator + "pdf_exporter.py";

        try {
            ProcessBuilder pb = new ProcessBuilder("python3", scriptPath, raceName);
            pb.environment().put("PYTHONIOENCODING", "utf-8");
            pb.redirectErrorStream(false);

            Process proc = pb.start();

            // stdout からバイナリ読み込み
            ByteArrayOutputStream pdfBuf = new ByteArrayOutputStream();
            try (InputStream is = proc.getInputStream()) {
                byte[] chunk = new byte[4096];
                int read;
                while ((read = is.read(chunk)) != -1) {
                    pdfBuf.write(chunk, 0, read);
                }
            }

            // stderr はログ用に読み捨て（ブロック回避）
            try (BufferedReader err = new BufferedReader(
                    new InputStreamReader(proc.getErrorStream(), StandardCharsets.UTF_8))) {
                err.lines().forEach(l -> {}); // 読み捨て
            }

            int exit = proc.waitFor();

            if (exit != 0 || pdfBuf.size() == 0) {
                return ResponseEntity.internalServerError()
                        .body(("PDF生成に失敗しました (exit=" + exit + ")").getBytes(StandardCharsets.UTF_8));
            }

            // ファイル名: 日本語対応 RFC 5987
            String encoded = URLEncoder.encode(raceName + "_予想.pdf", "UTF-8").replace("+", "%20");
            String disposition = "attachment; filename*=UTF-8''" + encoded;

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_PDF);
            headers.set(HttpHeaders.CONTENT_DISPOSITION, disposition);

            return ResponseEntity.ok().headers(headers).body(pdfBuf.toByteArray());

        } catch (Exception e) {
            return ResponseEntity.internalServerError()
                    .body(("例外: " + e.getMessage()).getBytes(StandardCharsets.UTF_8));
        }
    }

    // LINE通知（/prediction/notify?raceName=xxx）
    @PostMapping("/notify")
    public String sendLineNotify(
            @RequestParam String raceName,
            RedirectAttributes ra) {

        String scriptPath = pythonScriptDir + File.separator + "notifier.py";
        try {
            ProcessBuilder pb = new ProcessBuilder("python3", scriptPath, "send", raceName);
            pb.environment().put("PYTHONIOENCODING", "utf-8");
            pb.redirectErrorStream(true);
            Process proc = pb.start();

            StringBuilder sb = new StringBuilder();
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(proc.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) sb.append(line).append("\n");
            }
            int exit = proc.waitFor();
            if (exit == 0) {
                ra.addFlashAttribute("notifySuccess", "LINE通知を送信しました ✅");
            } else {
                ra.addFlashAttribute("notifyError", "LINE送信失敗: " + sb.toString().trim());
            }
        } catch (Exception e) {
            ra.addFlashAttribute("notifyError", "例外: " + e.getMessage());
        }
        return "redirect:/predict-v2?raceName=" + URLEncoder.encode(raceName, StandardCharsets.UTF_8);
    }
}
