package com.faceprediction.controller;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

import com.faceprediction.entity.PredictionAccuracy;
import com.faceprediction.entity.PredictionResult;
import com.faceprediction.repository.PredictionAccuracyRepository;
import com.faceprediction.repository.PredictionResultRepository;
import com.faceprediction.repository.RaceSpecificResultRepository;

@Controller
@RequestMapping("/accuracy")
public class AccuracyController {

    private final PredictionAccuracyRepository accuracyRepo;
    private final PredictionResultRepository   predictionRepo;
    private final RaceSpecificResultRepository  v2ResultRepo;
    private final JdbcTemplate                  jdbc;

    private static final Map<String, String> CATEGORY_LABELS = new LinkedHashMap<>();
    static {
        CATEGORY_LABELS.put("sprint", "短距離（〜1400m）");
        CATEGORY_LABELS.put("mile",   "マイル（1600〜1800m）");
        CATEGORY_LABELS.put("middle", "中距離（2000〜2200m）");
        CATEGORY_LABELS.put("long",   "長距離（2400m〜）");
        CATEGORY_LABELS.put("dirt",   "ダート");
        CATEGORY_LABELS.put("all",    "全カテゴリ");
    }

    @Autowired
    public AccuracyController(PredictionAccuracyRepository accuracyRepo,
                               PredictionResultRepository predictionRepo,
                               RaceSpecificResultRepository v2ResultRepo,
                               JdbcTemplate jdbc) {
        this.accuracyRepo  = accuracyRepo;
        this.predictionRepo = predictionRepo;
        this.v2ResultRepo   = v2ResultRepo;
        this.jdbc           = jdbc;
    }

    @GetMapping
    public String showAccuracy(Model model) {

        // ── 旧システム 全体統計 ──────────────────────────
        List<Object[]> overallList = accuracyRepo.findOverallStats();
        Object[] overall = overallList.isEmpty() ? new Object[]{0L, 0L, 0L} : overallList.get(0);
        long totalRaces = overall[0] != null ? ((Number) overall[0]).longValue() : 0;
        long winHits    = overall[1] != null ? ((Number) overall[1]).longValue() : 0;
        long top5Hits   = overall[2] != null ? ((Number) overall[2]).longValue() : 0;

        model.addAttribute("totalRaces",   totalRaces);
        model.addAttribute("winHitRate",   totalRaces > 0 ? Math.round(winHits  * 1000.0 / totalRaces) / 10.0 : 0.0);
        model.addAttribute("top5HitRate",  totalRaces > 0 ? Math.round(top5Hits * 1000.0 / totalRaces) / 10.0 : 0.0);

        // ── 旧システム カテゴリ別統計 ────────────────────
        List<Object[]> catStats = accuracyRepo.findCategoryStats();
        List<Map<String, Object>> categoryRows = new ArrayList<>();
        for (Object[] row : catStats) {
            String cat = (String) row[0];
            long races = row[1] != null ? ((Number) row[1]).longValue() : 0;
            long wh    = row[2] != null ? ((Number) row[2]).longValue() : 0;
            long th    = row[3] != null ? ((Number) row[3]).longValue() : 0;
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("category",    CATEGORY_LABELS.getOrDefault(cat, cat));
            m.put("races",       races);
            m.put("winHitRate",  races > 0 ? Math.round(wh * 1000.0 / races) / 10.0 : 0.0);
            m.put("top5HitRate", races > 0 ? Math.round(th * 1000.0 / races) / 10.0 : 0.0);
            categoryRows.add(m);
        }
        model.addAttribute("categoryRows", categoryRows);

        // ── 旧システム 直近記録 ──────────────────────────
        List<PredictionAccuracy> recent = accuracyRepo.findRecordedResults();
        model.addAttribute("recentResults",
            recent.stream().limit(20).collect(Collectors.toList()));

        // ── 新システム（顔面傾向分析）統計 ───────────────
        try {
            List<Map<String, Object>> v2Stats = jdbc.queryForList(
                "SELECT COUNT(DISTINCT race_name) AS total_races," +
                " SUM(CASE WHEN hit=TRUE THEN 1 ELSE 0 END) AS win_hits," +
                " SUM(CASE WHEN top5_hit=TRUE THEN 1 ELSE 0 END) AS top5_hits" +
                " FROM race_specific_accuracy WHERE predicted_rank = 1");
            if (!v2Stats.isEmpty()) {
                Map<String, Object> v2 = v2Stats.get(0);
                long v2Total = v2.get("total_races") != null ? ((Number)v2.get("total_races")).longValue() : 0;
                long v2Win   = v2.get("win_hits")    != null ? ((Number)v2.get("win_hits")).longValue()    : 0;
                long v2Top5  = v2.get("top5_hits")   != null ? ((Number)v2.get("top5_hits")).longValue()   : 0;
                model.addAttribute("v2TotalRaces",  v2Total);
                model.addAttribute("v2WinHitRate",  v2Total > 0 ? Math.round(v2Win  * 1000.0 / v2Total) / 10.0 : 0.0);
                model.addAttribute("v2Top5HitRate", v2Total > 0 ? Math.round(v2Top5 * 1000.0 / v2Total) / 10.0 : 0.0);
            } else {
                model.addAttribute("v2TotalRaces", 0L);
                model.addAttribute("v2WinHitRate", 0.0);
                model.addAttribute("v2Top5HitRate", 0.0);
            }

            // 新システム 直近記録（予想1位のみ表示）
            List<Map<String, Object>> v2Recent = jdbc.queryForList(
                "SELECT DISTINCT ON (race_name) race_name, predicted_rank, horse_name," +
                " actual_rank, hit, top5_hit, score, data_source, recorded_at" +
                " FROM race_specific_accuracy WHERE predicted_rank = 1" +
                " ORDER BY race_name, recorded_at DESC LIMIT 30");
            model.addAttribute("v2RecentResults", v2Recent);

            // 未記録レース（予想はあるが的中記録がないもの）
            List<Map<String, Object>> v2Pending = jdbc.queryForList(
                "SELECT rsr.race_name, COUNT(*) AS horse_count," +
                " MIN(rsr.created_at)::date AS predicted_on" +
                " FROM race_specific_result rsr" +
                " WHERE NOT EXISTS (" +
                "   SELECT 1 FROM race_specific_accuracy rsa" +
                "   WHERE rsa.race_name = rsr.race_name" +
                " )" +
                " GROUP BY rsr.race_name" +
                " ORDER BY MIN(rsr.created_at) DESC");
            model.addAttribute("v2PendingRaces", v2Pending);

            // 記録済みレースの馬名一覧（手動記録フォームの補助用）
            List<Map<String, Object>> v2AllRaces = jdbc.queryForList(
                "SELECT DISTINCT rsr.race_name, rsr.horse_name, rsr.rank_position" +
                " FROM race_specific_result rsr" +
                " ORDER BY rsr.race_name, rsr.rank_position");
            // race_name → horses map に変換
            Map<String, List<String>> raceHorseMap = new LinkedHashMap<>();
            for (Map<String, Object> row : v2AllRaces) {
                String rn = (String) row.get("race_name");
                String hn = (String) row.get("horse_name");
                raceHorseMap.computeIfAbsent(rn, k -> new ArrayList<>()).add(hn);
            }
            model.addAttribute("v2RaceHorseMap", raceHorseMap);

        } catch (Exception e) {
            model.addAttribute("v2TotalRaces", 0L);
            model.addAttribute("v2WinHitRate", 0.0);
            model.addAttribute("v2Top5HitRate", 0.0);
            model.addAttribute("v2RecentResults", List.of());
            model.addAttribute("v2PendingRaces", List.of());
            model.addAttribute("v2RaceHorseMap", Map.of());
        }

        // ── フォーム用：旧システム予想済みレース名 ─────────
        List<String> raceNames = predictionRepo.findDistinctRaceNames();
        model.addAttribute("raceNames", raceNames);

        return "accuracy/index";
    }

    // ── 旧システム: 手動結果記録 ────────────────────────
    @PostMapping("/record")
    public String recordResult(
            @RequestParam String raceName,
            @RequestParam String actualWinner,
            RedirectAttributes ra) {

        List<PredictionResult> predictions =
            predictionRepo.findByTargetRaceNameOrderByRankPosition(raceName);
        if (predictions.isEmpty()) {
            ra.addFlashAttribute("error", "予想データが見つかりません: " + raceName);
            return "redirect:/accuracy";
        }

        boolean top5Hit = predictions.stream()
            .limit(5).anyMatch(p -> p.getHorseName().equals(actualWinner));
        boolean hit1st  = !predictions.isEmpty()
            && predictions.get(0).getHorseName().equals(actualWinner);

        for (PredictionResult p : predictions) {
            PredictionAccuracy acc = new PredictionAccuracy();
            acc.setPredictionId(p.getId());
            acc.setRaceName(raceName);
            acc.setRaceDate(p.getTargetRaceDate());
            acc.setRaceCategory(p.getRaceCategory());
            acc.setHorseName(p.getHorseName());
            acc.setPredictedRank(p.getRankPosition());
            acc.setActualRank(p.getHorseName().equals(actualWinner) ? 1 : null);
            acc.setHit(hit1st && p.getRankPosition() == 1);
            acc.setTop5Hit(top5Hit);
            acc.setFinalScore(p.getFinalScore());
            accuracyRepo.save(acc);
        }

        ra.addFlashAttribute("success",
            raceName + " の結果を記録しました。1位的中: " + (hit1st ? "✓" : "✗")
            + "  TOP5的中: " + (top5Hit ? "✓" : "✗"));
        return "redirect:/accuracy";
    }

    // ── 新システム: 手動結果記録 ────────────────────────
    // 1〜3着を入力して race_specific_accuracy に書き込む
    @PostMapping("/record-v2")
    public String recordV2(
            @RequestParam String raceName,
            @RequestParam String first,
            @RequestParam(required = false, defaultValue = "") String second,
            @RequestParam(required = false, defaultValue = "") String third,
            RedirectAttributes ra) {

        if (raceName.isBlank() || first.isBlank()) {
            ra.addFlashAttribute("error", "レース名と1着馬名は必須です");
            return "redirect:/accuracy#tab-new";
        }

        try {
            // 予想データ取得
            List<Map<String, Object>> predictions = jdbc.queryForList(
                "SELECT horse_name, rank_position, score, data_source" +
                " FROM race_specific_result WHERE race_name = ?" +
                " ORDER BY rank_position",
                raceName);

            if (predictions.isEmpty()) {
                ra.addFlashAttribute("error", "予想データが見つかりません: " + raceName);
                return "redirect:/accuracy#tab-new";
            }

            String first_  = first.trim();
            String second_ = second.trim();
            String third_  = third.trim();

            List<String> top5Names = predictions.stream()
                .limit(5).map(p -> (String) p.get("horse_name")).collect(Collectors.toList());

            boolean hit1st  = predictions.get(0).get("horse_name").equals(first_);
            boolean top5Hit = top5Names.contains(first_)
                           || (!second_.isEmpty() && top5Names.contains(second_))
                           || (!third_.isEmpty() && top5Names.contains(third_));

            // 既存レコードを削除して上書き
            jdbc.update("DELETE FROM race_specific_accuracy WHERE race_name = ?", raceName);

            for (Map<String, Object> p : predictions) {
                String horseName = (String) p.get("horse_name");
                int predRank     = ((Number) p.get("rank_position")).intValue();
                Double score     = p.get("score") != null ? ((Number) p.get("score")).doubleValue() : null;
                String dataSrc   = (String) p.get("data_source");

                Integer actualRank = null;
                if (horseName.equals(first_))                          actualRank = 1;
                else if (!second_.isEmpty() && horseName.equals(second_)) actualRank = 2;
                else if (!third_.isEmpty()  && horseName.equals(third_))  actualRank = 3;

                jdbc.update(
                    "INSERT INTO race_specific_accuracy" +
                    " (race_name, horse_name, predicted_rank, actual_rank, hit, top5_hit, score, data_source, recorded_at)" +
                    " VALUES (?,?,?,?,?,?,?,?,NOW())",
                    raceName, horseName, predRank, actualRank,
                    hit1st && predRank == 1, top5Hit, score, dataSrc);
            }

            String msg = raceName + " 記録完了 — 1位的中: " + (hit1st ? "✅ HIT" : "✗ MISS")
                       + "  TOP5的中: " + (top5Hit ? "✅ HIT" : "✗ MISS");
            ra.addFlashAttribute("success", msg);

        } catch (Exception e) {
            ra.addFlashAttribute("error", "記録エラー: " + e.getMessage());
        }
        return "redirect:/accuracy";
    }
}
