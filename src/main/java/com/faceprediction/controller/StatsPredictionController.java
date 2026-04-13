package com.faceprediction.controller;

import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

@Controller
@RequestMapping("/stats-predict")
public class StatsPredictionController {

    @Value("${python.script.dir}")
    private String pythonScriptDir;

    @Autowired
    private JdbcTemplate jdbc;

    private static final ConcurrentHashMap<String, SseEmitter> emitters = new ConcurrentHashMap<>();
    private static final ConcurrentHashMap<String, Boolean>    running  = new ConcurrentHashMap<>();
    private static final ExecutorService executor = Executors.newCachedThreadPool();
    private static final ObjectMapper    mapper   = new ObjectMapper();

    // ──────────────────────────────────────────────
    // GET /stats-predict  — 結果表示
    // ──────────────────────────────────────────────
    @GetMapping
    public String show(@RequestParam(required = false) String raceName, Model model) {

        // 分析済みレース一覧
        List<String> raceNames = jdbc.queryForList(
            "SELECT race_name FROM stats_prediction GROUP BY race_name ORDER BY MAX(created_at) DESC",
            String.class);
        model.addAttribute("raceNames", raceNames);

        // 出走馬がいるレース（未分析含む）
        List<String> entryRaces = jdbc.queryForList(
            "SELECT race_name FROM race_entry GROUP BY race_name ORDER BY MIN(race_date), race_name",
            String.class);
        model.addAttribute("entryRaces", entryRaces);

        String selected = raceName;
        if (selected == null && !raceNames.isEmpty()) selected = raceNames.get(0);
        model.addAttribute("selectedRace", selected);

        if (selected != null) {
            List<Map<String, Object>> results = jdbc.queryForList(
                "SELECT horse_name, horse_number, jockey_name, rank_position, score, score_detail, comment, " +
                "image_path, face_comment, face_score " +
                "FROM stats_prediction WHERE race_name = ? ORDER BY rank_position",
                selected);

            // score_detail JSON → Map に変換
            List<Map<String, Object>> enriched = new ArrayList<>();
            for (Map<String, Object> row : results) {
                Map<String, Object> r = new LinkedHashMap<>(row);
                String detailJson = (String) row.get("score_detail");
                if (detailJson != null && !detailJson.isBlank()) {
                    try {
                        Map<String, String> detail = mapper.readValue(
                            detailJson, new TypeReference<Map<String, String>>() {});
                        r.put("detail", detail);
                    } catch (Exception ignored) {}
                }
                enriched.add(r);
            }
            model.addAttribute("results", enriched);
        } else {
            model.addAttribute("results", List.of());
        }

        return "prediction/stats_predict";
    }

    // ──────────────────────────────────────────────
    // GET /stats-predict/log  — SSE ログ
    // ──────────────────────────────────────────────
    @GetMapping(value = "/log", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    @ResponseBody
    public SseEmitter streamLog(@RequestParam String key) {
        SseEmitter emitter = new SseEmitter(20 * 60 * 1000L);
        emitters.put(key, emitter);
        emitter.onCompletion(() -> emitters.remove(key));
        emitter.onTimeout(()    -> emitters.remove(key));
        return emitter;
    }

    // ──────────────────────────────────────────────
    // POST /stats-predict/run  — 分析実行
    // ──────────────────────────────────────────────
    @PostMapping("/run")
    @ResponseBody
    public ResponseEntity<Map<String, Object>> run(@RequestParam String raceName) {
        Map<String, Object> resp = new LinkedHashMap<>();
        String key = "stats_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12);

        if (running.getOrDefault(key, false)) {
            resp.put("error", "すでに実行中です");
            return ResponseEntity.ok(resp);
        }

        String script = pythonScriptDir + File.separator + "stats_predictor.py";
        List<String> cmd = List.of("python3", script, raceName);
        startScript(key, cmd);

        resp.put("key", key);
        resp.put("message", "統計予想を開始しました");
        return ResponseEntity.ok(resp);
    }

    // ──────────────────────────────────────────────
    // POST /stats-predict/run-face  — 顔面分析実行
    // ──────────────────────────────────────────────
    @PostMapping("/run-face")
    @ResponseBody
    public ResponseEntity<Map<String, Object>> runFace(@RequestParam String raceName) {
        Map<String, Object> resp = new LinkedHashMap<>();
        String key = "face_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12);

        if (running.getOrDefault(key, false)) {
            resp.put("error", "すでに顔面分析が実行中です");
            return ResponseEntity.ok(resp);
        }

        String script = pythonScriptDir + File.separator + "face_analyzer_local.py";
        List<String> cmd = List.of("python3", script, raceName);
        startScript(key, cmd);

        resp.put("key", key);
        resp.put("message", "顔面分析を開始しました");
        return ResponseEntity.ok(resp);
    }

    private void startScript(String key, List<String> cmd) {
        running.put(key, true);
        executor.submit(() -> {
            try {
                ProcessBuilder pb = new ProcessBuilder(cmd);
                pb.environment().put("PYTHONUNBUFFERED", "1");
                pb.environment().put("PYTHONIOENCODING", "utf-8");
                pb.redirectErrorStream(true);
                Process proc = pb.start();

                try (BufferedReader reader = new BufferedReader(
                        new InputStreamReader(proc.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) {
                        if (!line.startsWith("RESULT:")) {
                            sendLog(key, line);
                        }
                    }
                }
                proc.waitFor();
                sendLog(key, "=== 完了 ===");
            } catch (Exception e) {
                sendLog(key, "[エラー] " + e.getMessage());
            } finally {
                running.put(key, false);
                sendLog(key, "__DONE__");
                SseEmitter em = emitters.remove(key);
                if (em != null) em.complete();
            }
        });
    }

    private void sendLog(String key, String line) {
        SseEmitter em = emitters.get(key);
        if (em != null) {
            try { em.send(SseEmitter.event().data(line)); }
            catch (Exception e) { emitters.remove(key); }
        }
    }
}
