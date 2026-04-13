package com.faceprediction.controller;

import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import com.fasterxml.jackson.databind.ObjectMapper;

import com.faceprediction.repository.RaceSpecificPredictionRepository;

@Controller
@RequestMapping("/paddock")
public class PaddockAnalysisController {

    @Value("${python.script.dir}")
    private String pythonScriptDir;

    @Value("${upload.dir}")
    private String uploadDir;

    @Autowired
    private RaceSpecificPredictionRepository patternRepo;

    private static final ConcurrentHashMap<String, SseEmitter> emitters  = new ConcurrentHashMap<>();
    private static final ConcurrentHashMap<String, Boolean>    running   = new ConcurrentHashMap<>();
    private static final ConcurrentHashMap<String, Object>     results   = new ConcurrentHashMap<>();
    private static final ExecutorService executor = Executors.newCachedThreadPool();
    private static final ObjectMapper    mapper   = new ObjectMapper();

    // 見せるフォーム
    @GetMapping
    public String showForm(Model model) {
        List<String> raceNames = patternRepo.findAllRaceNames();
        model.addAttribute("raceNames", raceNames);
        return "prediction/paddock";
    }

    // SSE ログストリーム
    @GetMapping(value = "/log", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    @ResponseBody
    public SseEmitter streamLog(@RequestParam String key) {
        SseEmitter emitter = new SseEmitter(15 * 60 * 1000L); // 15分
        emitters.put(key, emitter);
        emitter.onCompletion(() -> emitters.remove(key));
        emitter.onTimeout(()    -> emitters.remove(key));
        return emitter;
    }

    // 分析結果JSON取得（JavaScript がポーリング）
    @GetMapping("/result")
    @ResponseBody
    public ResponseEntity<Object> getResult(@RequestParam String key) {
        Object r = results.get(key);
        if (r == null) {
            return ResponseEntity.noContent().build();
        }
        return ResponseEntity.ok(r);
    }

    // アップロード + 分析開始
    @PostMapping("/analyze")
    @ResponseBody
    public ResponseEntity<java.util.Map<String, Object>> analyze(
            @RequestParam MultipartFile image,
            @RequestParam String raceName,
            @RequestParam(defaultValue = "") String horseName) {

        java.util.Map<String, Object> resp = new java.util.LinkedHashMap<>();

        if (image.isEmpty()) {
            resp.put("error", "画像ファイルを選択してください");
            return ResponseEntity.badRequest().body(resp);
        }

        // ファイル保存
        String origName = image.getOriginalFilename();
        String ext = (origName != null && origName.contains("."))
            ? origName.substring(origName.lastIndexOf('.'))
            : ".jpg";
        String fileName = "paddock_" + UUID.randomUUID().toString().replace("-", "") + ext;

        try {
            Path paddockDir = Paths.get(uploadDir, "paddock");
            Files.createDirectories(paddockDir);
            Path dest = paddockDir.resolve(fileName);
            Files.copy(image.getInputStream(), dest, StandardCopyOption.REPLACE_EXISTING);

            // 分析キー（レース名ベース、衝突防止にUUID短縮）
            String key = "paddock_" + Math.abs(raceName.hashCode()) + "_" + UUID.randomUUID().toString().substring(0, 8);
            results.remove(key);

            // バックグラウンド実行
            startAnalysis(key, dest.toAbsolutePath().toString(), raceName, horseName);

            resp.put("key", key);
            resp.put("message", "分析を開始しました");
            return ResponseEntity.ok(resp);

        } catch (Exception e) {
            resp.put("error", "ファイル保存エラー: " + e.getMessage());
            return ResponseEntity.status(500).body(resp);
        }
    }

    // バックグラウンド分析
    private void startAnalysis(String key, String imagePath, String raceName, String horseName) {
        running.put(key, true);
        executor.submit(() -> {
            try {
                String script = pythonScriptDir + File.separator + "paddock_analyzer.py";
                List<String> cmd = new ArrayList<>();
                cmd.add("python3");
                cmd.add(script);
                cmd.add("--image"); cmd.add(imagePath);
                cmd.add("--race");  cmd.add(raceName);
                if (horseName != null && !horseName.isBlank()) {
                    cmd.add("--horse"); cmd.add(horseName);
                }

                ProcessBuilder pb = new ProcessBuilder(cmd);
                pb.environment().put("PYTHONUNBUFFERED",  "1");
                pb.environment().put("PYTHONIOENCODING", "utf-8");
                pb.redirectErrorStream(true);
                Process proc = pb.start();

                try (BufferedReader reader = new BufferedReader(
                        new InputStreamReader(proc.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) {
                        // RESULT: 行をパース
                        if (line.startsWith("RESULT:")) {
                            try {
                                String json = line.substring("RESULT:".length());
                                Object parsed = mapper.readValue(json, Object.class);
                                results.put(key, parsed);
                            } catch (Exception ex) {
                                sendLog(key, "[警告] RESULT解析エラー: " + ex.getMessage());
                            }
                        } else {
                            sendLog(key, line);
                        }
                    }
                }
                proc.waitFor();

            } catch (Exception e) {
                sendLog(key, "[エラー] " + e.getMessage());
                java.util.Map<String, Object> errResult = new java.util.LinkedHashMap<>();
                errResult.put("success", false);
                errResult.put("error", e.getMessage());
                results.put(key, errResult);
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
