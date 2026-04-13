package com.faceprediction.controller;

import java.io.File;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.Map;

import javax.sql.DataSource;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseBody;

import com.faceprediction.repository.HorseFaceFeatureRepository;
import com.faceprediction.repository.PredictionResultRepository;
import com.faceprediction.repository.RaceEntryRepository;

@Controller
@RequestMapping("/health")
public class HealthController {

    @Autowired private DataSource dataSource;
    @Autowired private HorseFaceFeatureRepository featureRepo;
    @Autowired private PredictionResultRepository predictionRepo;
    @Autowired private RaceEntryRepository entryRepo;

    @Value("${python.script.dir}")
    private String pythonScriptDir;

    @Value("${upload.dir}")
    private String uploadDir;

    @GetMapping
    public String showHealth(Model model) {
        // DB接続確認
        boolean dbOk = false;
        String dbError = null;
        try (var conn = dataSource.getConnection()) {
            dbOk = conn.isValid(3);
        } catch (Exception e) {
            dbError = e.getMessage();
        }

        // ANTHROPIC_API_KEY確認
        String apiKey = System.getenv("ANTHROPIC_API_KEY");
        boolean apiKeySet = apiKey != null && !apiKey.isEmpty() && !apiKey.startsWith("sk-ant-api03-XXXX");

        // LINE_NOTIFY_TOKEN確認
        String lineToken = System.getenv("LINE_NOTIFY_TOKEN");
        boolean lineTokenSet = lineToken != null && !lineToken.isEmpty()
                && !lineToken.contains("ここに");

        // Python スクリプトディレクトリ確認
        File scriptDir = new File(pythonScriptDir);
        boolean scriptDirOk = scriptDir.exists() && scriptDir.isDirectory();

        // 画像ディレクトリ確認
        File imgDir = new File(uploadDir);
        boolean imgDirOk = imgDir.exists();
        long imgDirMB = 0;
        if (imgDirOk) {
            imgDirMB = dirSizeMB(imgDir);
        }

        // スクリプトファイル存在確認
        Map<String, Boolean> scripts = new LinkedHashMap<>();
        scripts.put("scraper.py",       new File(pythonScriptDir + "/scraper.py").exists());
        scripts.put("face_analyzer.py", new File(pythonScriptDir + "/face_analyzer.py").exists());
        scripts.put("entry_fetcher.py", new File(pythonScriptDir + "/entry_fetcher.py").exists());
        scripts.put("predictor.py",     new File(pythonScriptDir + "/predictor.py").exists());

        // DB件数
        long featureCount    = featureRepo.count();
        long predictionCount = predictionRepo.count();
        long entryCount      = entryRepo.count();

        // 現在時刻
        String checkedAt = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));

        model.addAttribute("dbOk",          dbOk);
        model.addAttribute("dbError",        dbError);
        model.addAttribute("apiKeySet",      apiKeySet);
        model.addAttribute("lineTokenSet",   lineTokenSet);
        model.addAttribute("scriptDirOk",    scriptDirOk);
        model.addAttribute("scriptDirPath",  pythonScriptDir);
        model.addAttribute("imgDirOk",       imgDirOk);
        model.addAttribute("imgDirPath",     uploadDir);
        model.addAttribute("imgDirMB",       imgDirMB);
        model.addAttribute("scripts",        scripts);
        model.addAttribute("featureCount",   featureCount);
        model.addAttribute("predictionCount",predictionCount);
        model.addAttribute("entryCount",     entryCount);
        model.addAttribute("checkedAt",      checkedAt);

        return "health/index";
    }

    /** JSON用エンドポイント（外部監視等に利用可） */
    @GetMapping(value = "/api", produces = "application/json")
    @ResponseBody
    public Map<String, Object> healthApi() {
        Map<String, Object> result = new LinkedHashMap<>();
        boolean dbOk = false;
        try (var conn = dataSource.getConnection()) {
            dbOk = conn.isValid(3);
        } catch (Exception ignored) {}
        result.put("db", dbOk ? "OK" : "NG");
        result.put("api_key_set", System.getenv("ANTHROPIC_API_KEY") != null);
        result.put("checked_at", LocalDateTime.now().toString());
        return result;
    }

    private long dirSizeMB(File dir) {
        long size = 0;
        File[] files = dir.listFiles();
        if (files != null) {
            for (File f : files) {
                size += f.isDirectory() ? dirSizeMB(f) * 1024 * 1024 : f.length();
            }
        }
        return size / (1024 * 1024);
    }
}
