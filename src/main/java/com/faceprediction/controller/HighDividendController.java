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
import org.springframework.dao.DataAccessException;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@Controller
@RequestMapping("/high-dividend")
public class HighDividendController {

    @Autowired
    private JdbcTemplate jdbcTemplate;

    private static final ConcurrentHashMap<String, SseEmitter>  emitters = new ConcurrentHashMap<>();
    private static final ConcurrentHashMap<String, Boolean>     running  = new ConcurrentHashMap<>();
    private static final ConcurrentHashMap<String, List<String>> logs    = new ConcurrentHashMap<>();
    private static final int MAX_LOG_LINES = 2000;
    private static final ExecutorService executor = Executors.newCachedThreadPool();
    private static final String STREAM_KEY = "high_dividend";

    // ── GET /high-dividend ─────────────────────────────────────
    @GetMapping
    public String index(Model model) {
        model.addAttribute("currentPage", "high-dividend");
        return "prediction/high_dividend";
    }

    // ── GET /high-dividend/run-stream ──────────────────────────
    @GetMapping(value = "/run-stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter runStream() {
        SseEmitter emitter = new SseEmitter(1800000L); // 30分タイムアウト

        // 既に実行中の場合は既存エミッターに追加し既存ログを送信
        if (running.getOrDefault(STREAM_KEY, false)) {
            emitters.put(STREAM_KEY, emitter);
            List<String> existing = logs.getOrDefault(STREAM_KEY, List.of());
            executor.submit(() -> {
                try {
                    for (String line : existing) {
                        emitter.send(SseEmitter.event().data(line));
                    }
                } catch (Exception ignored) {}
            });
            return emitter;
        }

        emitters.put(STREAM_KEY, emitter);
        startScript(STREAM_KEY,
                List.of("python3", "python/high_dividend_selector.py"),
                System.getProperty("user.dir"));

        return emitter;
    }

    // ── GET /high-dividend/result ──────────────────────────────
    @GetMapping("/result")
    @ResponseBody
    public ResponseEntity<Map<String, Object>> result() {
        try {
            List<Map<String, Object>> rows = jdbcTemplate.queryForList(
                "SELECT race_name, race_id, horse_count, favorite_odds, chaos_score," +
                " selection_reason, analyzed_at" +
                " FROM high_dividend_selection" +
                " ORDER BY analyzed_at DESC" +
                " LIMIT 1");

            if (rows.isEmpty()) {
                return ResponseEntity.ok(Map.of());
            }

            Map<String, Object> row = rows.get(0);
            Map<String, Object> resp = new LinkedHashMap<>();
            resp.put("raceName",        row.get("race_name"));
            resp.put("raceId",          row.get("race_id"));
            resp.put("horseCount",      row.get("horse_count"));
            resp.put("favoriteOdds",    row.get("favorite_odds"));
            resp.put("chaosScore",      row.get("chaos_score"));
            resp.put("selectionReason", row.get("selection_reason"));
            resp.put("analyzedAt",      row.get("analyzed_at"));
            return ResponseEntity.ok(resp);

        } catch (DataAccessException e) {
            // テーブルが存在しない / データなし
            return ResponseEntity.ok(Map.of());
        }
    }

    // ── 内部: スクリプト起動 ──────────────────────────────────
    private void startScript(String key, List<String> cmd, String workDir) {
        running.put(key, true);
        logs.put(key, new ArrayList<>());

        executor.submit(() -> {
            Process proc = null;
            try {
                ProcessBuilder pb = new ProcessBuilder(cmd);
                pb.redirectErrorStream(true);
                pb.environment().put("PYTHONUNBUFFERED", "1");
                pb.environment().put("PYTHONIOENCODING", "utf-8");
                pb.directory(new File(workDir));
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
                            catch (Exception ignored) {}
                        }
                    }
                }
                proc.waitFor();
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
                    } catch (Exception ignored) {}
                }
            }
        });
    }
}
