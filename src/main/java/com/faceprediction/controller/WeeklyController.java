package com.faceprediction.controller;

import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.*;
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
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import javax.annotation.PreDestroy;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

@Controller
@RequestMapping("/weekly")
public class WeeklyController {

    private static final Logger log = LoggerFactory.getLogger(WeeklyController.class);

    @Value("${python.script.dir}")
    private String pythonScriptDir;

    @Autowired
    private JdbcTemplate jdbc;

    private static final ConcurrentHashMap<String, SseEmitter> emitters = new ConcurrentHashMap<>();
    private static final ConcurrentHashMap<String, Boolean>    running  = new ConcurrentHashMap<>();
    private static final ConcurrentHashMap<String, List<String>> logs   = new ConcurrentHashMap<>();
    private static final int MAX_LOG_LINES = 2000;
    private static final ExecutorService executor = Executors.newFixedThreadPool(4);
    private static final String PIPELINE_KEY = "weekly_pipeline";

    // ── GET /weekly ───────────────────────────────────────────
    @GetMapping
    public String index(@RequestParam(required = false) String raceName, Model model) {

        // 蓄積済みレース一覧（日付降順）
        List<Map<String, Object>> raceList = jdbc.queryForList(
            "SELECT sp.race_name," +
            "  MIN(re.race_date) AS race_date," +
            "  COUNT(DISTINCT sp.horse_name) AS horse_count," +
            "  COUNT(DISTINCT CASE WHEN sp.face_comment IS NOT NULL THEN sp.horse_name END) AS face_done," +
            "  MAX(sp.created_at) AS updated_at" +
            " FROM stats_prediction sp" +
            " LEFT JOIN race_entry re ON sp.race_name = re.race_name" +
            " GROUP BY sp.race_name" +
            " ORDER BY MIN(re.race_date) DESC NULLS LAST, MAX(sp.created_at) DESC");

        model.addAttribute("raceList",  raceList);
        model.addAttribute("selected",  raceName);
        model.addAttribute("isPipelineRunning", running.getOrDefault(PIPELINE_KEY, false));

        // 選択レースの予想結果
        List<Map<String, Object>> results = List.of();
        if (raceName != null && !raceName.isBlank()) {
            results = jdbc.queryForList(
                "SELECT horse_name, horse_number, jockey_name," +
                " rank_position, score, comment," +
                " image_path, face_comment, face_score" +
                " FROM stats_prediction WHERE race_name = ?" +
                " ORDER BY rank_position",
                raceName);
        }
        model.addAttribute("results", results);

        return "prediction/weekly";
    }

    // ── POST /weekly/run-pipeline ─────────────────────────────
    @PostMapping("/run-pipeline")
    @ResponseBody
    public ResponseEntity<Map<String, Object>> runPipeline() {
        Map<String, Object> resp = new LinkedHashMap<>();

        if (running.getOrDefault(PIPELINE_KEY, false)) {
            resp.put("error", "パイプラインが既に実行中です");
            return ResponseEntity.ok(resp);
        }

        String script = pythonScriptDir + File.separator + "weekly_pipeline.py";
        startScript(PIPELINE_KEY, List.of("python3", script));

        resp.put("key", PIPELINE_KEY);
        return ResponseEntity.ok(resp);
    }

    // ── GET /weekly/log ───────────────────────────────────────
    @GetMapping(value = "/log", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter log() {
        SseEmitter emitter = new SseEmitter(30 * 60 * 1000L); // 30分タイムアウト
        emitter.onCompletion(() -> emitters.remove(PIPELINE_KEY, emitter));
        emitter.onTimeout(()    -> emitters.remove(PIPELINE_KEY, emitter));
        emitter.onError(e       -> emitters.remove(PIPELINE_KEY, emitter));
        emitters.put(PIPELINE_KEY, emitter);

        // 既存ログを即時送信
        List<String> existing = logs.getOrDefault(PIPELINE_KEY, List.of());
        executor.submit(() -> {
            try {
                for (String line : existing) {
                    emitter.send(SseEmitter.event().data(line));
                }
                if (!running.getOrDefault(PIPELINE_KEY, false)) {
                    emitter.send(SseEmitter.event().data("__DONE__"));
                    emitter.complete();
                }
            } catch (Exception e) {
                log.warn("SSE既存ログ送信失敗: {}", e.getMessage());
            }
        });

        return emitter;
    }

    // ── 内部: スクリプト起動 ──────────────────────────────────
    private void startScript(String key, List<String> cmd) {
        running.put(key, true);
        logs.put(key, new ArrayList<>());

        executor.submit(() -> {
            Process proc = null;
            try {
                ProcessBuilder pb = new ProcessBuilder(cmd);
                pb.redirectErrorStream(true);
                pb.environment().put("PYTHONUNBUFFERED", "1");
                pb.environment().put("PYTHONIOENCODING", "utf-8");
                pb.directory(new File(pythonScriptDir));
                proc = pb.start();

                try (BufferedReader br = new BufferedReader(
                        new InputStreamReader(proc.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = br.readLine()) != null) {
                        List<String> logList = logs.get(key);
                        if (logList != null && logList.size() < MAX_LOG_LINES) {
                            logList.add(line);
                        }
                        SseEmitter em = emitters.get(key);
                        if (em != null) {
                            try { em.send(SseEmitter.event().data(line)); }
                            catch (Exception e) { log.warn("SSEログ送信失敗: {}", e.getMessage()); }
                        }
                    }
                }
                int exitCode = proc.waitFor();
                // 終了コードを評価して失敗をUIに伝える。
                // （従来は無視しており、パイプラインが exit 1 で失敗しても
                //   画面上は正常終了に見える偽成功だった）
                if (exitCode != 0) {
                    String failMsg = "❌ パイプラインは失敗で終了しました (exit=" + exitCode + ")。ログを確認してください。";
                    List<String> logList = logs.get(key);
                    if (logList != null && logList.size() < MAX_LOG_LINES) logList.add(failMsg);
                    SseEmitter em = emitters.get(key);
                    if (em != null) {
                        try { em.send(SseEmitter.event().data(failMsg)); }
                        catch (Exception e) { log.warn("SSE失敗通知送信失敗: {}", e.getMessage()); }
                    }
                }
            } catch (Exception e) {
                List<String> l = logs.get(key);
                if (l != null) l.add("エラー: " + e.getMessage());
            } finally {
                if (proc != null && proc.isAlive()) {
                    proc.destroyForcibly();
                }
                running.put(key, false);
                SseEmitter em = emitters.remove(key);
                if (em != null) {
                    try {
                        em.send(SseEmitter.event().data("__DONE__"));
                        em.complete();
                    } catch (Exception e) {
                        log.warn("SSE完了通知失敗: {}", e.getMessage());
                    }
                }
            }
        });
    }

    @PreDestroy
    public void shutdown() {
        executor.shutdownNow();
    }
}
