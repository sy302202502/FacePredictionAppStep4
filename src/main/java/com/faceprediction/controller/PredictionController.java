package com.faceprediction.controller;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileWriter;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.UUID;
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
import com.faceprediction.entity.RaceEntry;
import com.faceprediction.repository.RaceEntryRepository;
import com.faceprediction.service.PredictionService;

@Controller
@RequestMapping("/prediction")
public class PredictionController {

    private final PredictionService predictionService;
    private final RaceEntryRepository raceEntryRepository;

    @Value("${upload.dir}")
    private String uploadDir;

    @Value("${python.script.dir}")
    private String pythonScriptDir;

    @Autowired
    public PredictionController(PredictionService predictionService,
                                RaceEntryRepository raceEntryRepository) {
        this.predictionService = predictionService;
        this.raceEntryRepository = raceEntryRepository;
    }

    // 予想TOP5一覧（最新 or レース名で絞り込み）
    @GetMapping
    public String showPrediction(
            @RequestParam(required = false) String raceName,
            Model model) {

        List<String> raceNames = predictionService.getDistinctRaceNames();
        model.addAttribute("raceNames", raceNames);

        if (raceName != null && !raceName.isBlank()) {
            List<PredictionResult> results = predictionService.getPredictionsByRace(raceName);
            model.addAttribute("results", results);
            model.addAttribute("selectedRace", raceName);
        } else {
            List<PredictionResult> latest = predictionService.getLatestPredictions();
            model.addAttribute("results", latest.stream().limit(20).collect(Collectors.toList()));
            model.addAttribute("selectedRace", "");
        }

        return "prediction/index";
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

    // 予想実行フォーム表示
    @GetMapping("/run")
    public String showRunForm(
            @RequestParam(required = false) String selectedRace,
            Model model) {

        // 出走馬一覧に登録済みのレース名リスト
        List<Object[]> raceRows = raceEntryRepository.findDistinctRaces();
        List<String> raceNames = raceRows.stream()
                .map(r -> (String) r[0])
                .collect(Collectors.toList());
        model.addAttribute("entryRaceNames", raceNames);
        model.addAttribute("selectedRace", selectedRace != null ? selectedRace : "");

        // レースが選択されていれば出走馬リストを取得
        if (selectedRace != null && !selectedRace.isBlank()) {
            List<RaceEntry> entries = raceEntryRepository
                    .findByRaceNameOrderByHorseNumber(selectedRace);
            model.addAttribute("entries", entries);
        } else {
            model.addAttribute("entries", List.of());
        }

        return "prediction/run";
    }

    // 予想実行（predictor.py を呼び出す）
    @PostMapping("/run")
    public String runPrediction(
            @RequestParam String raceName,
            @RequestParam(required = false) List<String> selectedHorseIds,
            @RequestParam(required = false, defaultValue = "") String horseList,
            Model model) {

        // JSON構築: チェックボックス選択 or テキストエリア入力の両方に対応
        StringBuilder json = new StringBuilder("[");
        boolean first = true;

        if (selectedHorseIds != null && !selectedHorseIds.isEmpty()) {
            // チェックボックスから選択された馬IDで出走馬データを取得
            List<RaceEntry> entries = raceEntryRepository
                    .findByRaceNameOrderByHorseNumber(raceName);
            for (RaceEntry e : entries) {
                if (selectedHorseIds.contains(e.getHorseId())) {
                    String name = e.getHorseName().replace("\"", "\\\"");
                    String id   = e.getHorseId().replace("\"", "\\\"");
                    if (!first) json.append(",");
                    json.append("{\"name\":\"").append(name)
                        .append("\",\"horse_id\":\"").append(id).append("\"}");
                    first = false;
                }
            }
        } else {
            // テキストエリア入力（従来の手動入力形式）
            for (String line : horseList.split("\n")) {
                line = line.trim();
                if (line.isEmpty()) continue;
                String[] parts = line.split(",", 2);
                if (parts.length < 2) continue;
                String name = parts[0].trim().replace("\"", "\\\"");
                String id   = parts[1].trim().replace("\"", "\\\"");
                if (!first) json.append(",");
                json.append("{\"name\":\"").append(name)
                    .append("\",\"horse_id\":\"").append(id).append("\"}");
                first = false;
            }
        }
        json.append("]");

        File tempFile = null;
        String output = "";
        String errorOutput = "";
        boolean success = false;

        try {
            // 一時JSONファイルを作成
            tempFile = File.createTempFile("horses_" + UUID.randomUUID(), ".json");
            try (FileWriter fw = new FileWriter(tempFile)) {
                fw.write(json.toString());
            }

            // python スクリプトのパスを解決
            String scriptPath = pythonScriptDir + File.separator + "predictor.py";

            // ProcessBuilder でpythonを実行
            ProcessBuilder pb = new ProcessBuilder(
                "python3", scriptPath, raceName, tempFile.getAbsolutePath()
            );
            pb.environment().put("PYTHONIOENCODING", "utf-8");
            pb.redirectErrorStream(true);

            Process proc = pb.start();
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(proc.getInputStream(), "UTF-8"))) {
                StringBuilder sb = new StringBuilder();
                String line2;
                while ((line2 = reader.readLine()) != null) {
                    sb.append(line2).append("\n");
                }
                output = sb.toString();
            }
            int exitCode = proc.waitFor();
            success = (exitCode == 0);
        } catch (Exception e) {
            errorOutput = e.getMessage();
        } finally {
            if (tempFile != null) tempFile.delete();
        }

        // フォーム再表示用データを再ロード
        List<Object[]> raceRows = raceEntryRepository.findDistinctRaces();
        List<String> raceNames2 = raceRows.stream()
                .map(r -> (String) r[0]).collect(Collectors.toList());
        List<RaceEntry> entries = raceEntryRepository
                .findByRaceNameOrderByHorseNumber(raceName);
        model.addAttribute("entryRaceNames", raceNames2);
        model.addAttribute("entries", entries);
        model.addAttribute("selectedRace", raceName);
        model.addAttribute("raceName", raceName);
        model.addAttribute("output", output);
        model.addAttribute("errorOutput", errorOutput);
        model.addAttribute("success", success);
        return "prediction/run";
    }

    // PDF 出力（/prediction/pdf?raceName=xxx）
    @GetMapping("/pdf")
    @ResponseBody
    public ResponseEntity<byte[]> exportPdf(
            @RequestParam String raceName) {

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
        return "redirect:/prediction?raceName=" + java.net.URLEncoder.encode(raceName, StandardCharsets.UTF_8);
    }
}
