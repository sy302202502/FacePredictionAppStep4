package com.faceprediction.controller;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@Controller
@RequestMapping("/script")
public class ScriptController {

    @Value("${python.script.dir}")
    private String pythonScriptDir;

    // 実行中スクリプトのログをSSEで流すためのEmitter管理
    private static final ConcurrentHashMap<String, SseEmitter> emitters = new ConcurrentHashMap<>();
    private static final ConcurrentHashMap<String, Boolean> running = new ConcurrentHashMap<>();
    private static final ExecutorService executor = Executors.newCachedThreadPool();

    @GetMapping
    public String showScriptPage(Model model) {
        model.addAttribute("scraperRunning",  running.getOrDefault("scraper", false));
        model.addAttribute("analyzerRunning", running.getOrDefault("analyzer", false));
        return "script/index";
    }

    // SSEエンドポイント（ログのリアルタイム配信）
    @GetMapping(value = "/log", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    @ResponseBody
    public SseEmitter streamLog(@RequestParam String key) {
        SseEmitter emitter = new SseEmitter(30 * 60 * 1000L); // 30分タイムアウト
        emitters.put(key, emitter);
        emitter.onCompletion(() -> emitters.remove(key));
        emitter.onTimeout(()    -> emitters.remove(key));
        return emitter;
    }

    // スクレイピング実行
    @PostMapping("/scraper")
    public String runScraper(
            @RequestParam(defaultValue = "5") int years,
            Model model) {
        if (running.getOrDefault("scraper", false)) {
            model.addAttribute("message", "スクレイピングはすでに実行中です");
            return "script/index";
        }
        String script = pythonScriptDir + File.separator + "scraper.py";
        startScript("scraper", new String[]{"python3", script, String.valueOf(years)});
        return "redirect:/script?started=scraper";
    }

    // 顔分析実行
    @PostMapping("/analyzer")
    public String runAnalyzer(
            @RequestParam(defaultValue = "false") boolean winnersOnly,
            Model model) {
        if (running.getOrDefault("analyzer", false)) {
            model.addAttribute("message", "顔分析はすでに実行中です");
            return "script/index";
        }
        String script = pythonScriptDir + File.separator + "face_analyzer.py";
        String[] cmd = winnersOnly
            ? new String[]{"python3", script, "--winners-only"}
            : new String[]{"python3", script};
        startScript("analyzer", cmd);
        return "redirect:/script?started=analyzer";
    }

    // 出走馬取得実行
    @PostMapping("/entries")
    public String runEntryFetcher() {
        if (running.getOrDefault("entries", false)) {
            return "redirect:/script?started=entries";
        }
        String script = pythonScriptDir + File.separator + "entry_fetcher.py";
        startScript("entries", new String[]{"python3", script});
        return "redirect:/script?started=entries";
    }

    // 的中記録 自動取得
    @PostMapping("/result-fetch")
    public String runResultFetch() {
        if (running.getOrDefault("result_fetch", false)) {
            return "redirect:/script?started=result_fetch";
        }
        String script = pythonScriptDir + File.separator + "result_auto_fetcher.py";
        startScript("result_fetch", new String[]{"python3", script});
        return "redirect:/script?started=result_fetch";
    }

    // オッズ取得
    @PostMapping("/odds-fetch")
    public String runOddsFetch(@RequestParam(required = false) String raceName) {
        String key = "odds_fetch";
        if (running.getOrDefault(key, false)) {
            return "redirect:/script?started=" + key;
        }
        String script = pythonScriptDir + File.separator + "odds_fetcher.py";
        String[] cmd = raceName != null && !raceName.isBlank()
            ? new String[]{"python3", script, raceName}
            : new String[]{"python3", script};
        startScript(key, cmd);
        return "redirect:/script?started=" + key;
    }

    // 重み自動学習
    @PostMapping("/weight-learn")
    public String runWeightLearn() {
        if (running.getOrDefault("weight_learn", false)) {
            return "redirect:/script?started=weight_learn";
        }
        String script = pythonScriptDir + File.separator + "weight_learner.py";
        startScript("weight_learn", new String[]{"python3", script});
        return "redirect:/script?started=weight_learn";
    }

    // レース特化型分析（race_specific_analyzer.py）
    @PostMapping("/race-analyzer")
    public String runRaceAnalyzer(
            @RequestParam String raceName,
            @RequestParam(defaultValue = "10") int years,
            @RequestParam(defaultValue = "true") boolean supplement) {
        String key = "race_" + raceName.hashCode();
        if (running.getOrDefault(key, false)) {
            return "redirect:/script?started=" + key;
        }
        String script = pythonScriptDir + File.separator + "race_specific_analyzer.py";
        java.util.List<String> cmd = new java.util.ArrayList<>(
            java.util.Arrays.asList("python3", script, raceName, "--years", String.valueOf(years))
        );
        if (!supplement) cmd.add("--no-supplement");
        startScript(key, cmd.toArray(new String[0]));
        return "redirect:/script?started=" + java.net.URLEncoder.encode(key, java.nio.charset.StandardCharsets.UTF_8);
    }

    // 実行状態確認API
    @GetMapping("/status")
    @ResponseBody
    public java.util.Map<String, Boolean> getStatus() {
        java.util.Map<String, Boolean> status = new java.util.HashMap<>();
        status.put("scraper",      running.getOrDefault("scraper",      false));
        status.put("analyzer",     running.getOrDefault("analyzer",     false));
        status.put("entries",      running.getOrDefault("entries",      false));
        status.put("result_fetch",  running.getOrDefault("result_fetch",  false));
        status.put("odds_fetch",    running.getOrDefault("odds_fetch",    false));
        status.put("weight_learn",  running.getOrDefault("weight_learn",  false));
        // race_analyzer系は動的キーなのでいずれかが実行中か確認
        boolean raceRunning = running.entrySet().stream()
            .anyMatch(e -> e.getKey().startsWith("race_") && e.getValue());
        status.put("race_analyzer", raceRunning);
        return status;
    }

    // バックグラウンドでスクリプトを起動しSSEでログを流す
    private void startScript(String key, String[] cmd) {
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
                        sendLog(key, line);
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
            try {
                em.send(SseEmitter.event().data(line));
            } catch (Exception e) {
                emitters.remove(key);
            }
        }
    }
}
