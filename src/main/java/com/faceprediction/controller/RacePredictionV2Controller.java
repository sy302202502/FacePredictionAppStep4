package com.faceprediction.controller;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import com.faceprediction.entity.RaceOdds;
import com.faceprediction.entity.RaceSpecificResult;
import com.faceprediction.repository.RaceOddsRepository;

@Controller
@RequestMapping("/predict-v2")
public class RacePredictionV2Controller {

    @Autowired private RaceOddsRepository oddsRepo;
    @Autowired private JdbcTemplate       jdbc;

    @GetMapping
    public String show(@RequestParam(required = false) String raceName, Model model) {

        // 顔面分析済みレース一覧（stats_prediction を唯一の情報源にする）
        List<String> raceNames = jdbc.queryForList(
            "SELECT race_name FROM stats_prediction GROUP BY race_name ORDER BY MAX(created_at) DESC",
            String.class);
        model.addAttribute("raceNames", raceNames);

        String selected = raceName;
        if (selected == null && !raceNames.isEmpty()) {
            selected = raceNames.get(0);
        }
        model.addAttribute("selectedRace", selected);

        if (selected != null) {
            // 顔面スコア(主)＋統計スコア(差別化用)を取得
            // INNER JOIN race_entry で「現出走表に居る馬」だけを対象にする
            // = 出走取消馬は予想に表示されない
            List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT sp.horse_name, sp.image_path, sp.face_comment, sp.face_score, sp.score, sp.rank_position " +
                "FROM stats_prediction sp " +
                "INNER JOIN race_entry re " +
                "  ON re.race_name = sp.race_name AND re.horse_name = sp.horse_name " +
                "WHERE sp.race_name = ? " +
                "ORDER BY sp.rank_position ASC",
                selected);

            List<RaceSpecificResult> results = buildSpreadResults(rows);
            model.addAttribute("results", results);

            // オッズデータ（馬名→RaceOdds）。レース当日以外は空マップになる
            List<RaceOdds> oddsList = oddsRepo.findByRaceNameOrderByPopularityAsc(selected);
            Map<String, RaceOdds> oddsMap = oddsList.stream()
                .collect(Collectors.toMap(RaceOdds::getHorseName, o -> o, (a, b) -> a));
            model.addAttribute("oddsMap", oddsMap);
        } else {
            model.addAttribute("results", List.of());
            model.addAttribute("oddsMap", Map.of());
        }

        return "prediction/v2";
    }

    // 顔面スコアと統計スコアの配合比率（顔面主軸）
    private static final double FACE_WEIGHT  = 0.75;
    private static final double STATS_WEIGHT = 0.25;
    // レース内コントラスト強調係数（平均からの差を広げる）
    private static final double CONTRAST     = 1.9;
    private static final double SCORE_MIN    = 40.0;
    private static final double SCORE_MAX    = 99.0;

    /**
     * 顔面スコアを主軸に統計スコアで差別化し、レース内でコントラストを強調して
     * スコアの団子状態を解消する。顔面分析済みの馬のみ対象（未分析は末尾・スコア無し）。
     */
    private List<RaceSpecificResult> buildSpreadResults(List<Map<String, Object>> rows) {
        // 1. 各馬の合成スコアを計算
        List<RaceSpecificResult> analyzed = new ArrayList<>();
        List<RaceSpecificResult> unanalyzed = new ArrayList<>();
        List<Double> composites = new ArrayList<>();

        for (Map<String, Object> row : rows) {
            RaceSpecificResult r = new RaceSpecificResult();
            r.setHorseName((String) row.get("horse_name"));
            r.setImagePath((String) row.get("image_path"));
            r.setComment(toHeadlineFormat((String) row.get("face_comment")));

            Object fs = row.get("face_score");
            if (fs == null) {
                r.setScore(null);
                unanalyzed.add(r);
                continue;
            }
            double face  = ((Number) fs).doubleValue();
            Object ss = row.get("score");
            double stats = ss != null ? ((Number) ss).doubleValue() : face;
            double composite = face * FACE_WEIGHT + stats * STATS_WEIGHT;
            r.setScore(composite); // 一旦合成スコアを格納（後で引き伸ばす）
            analyzed.add(r);
            composites.add(composite);
        }

        // 2. レース内平均を基準にコントラストを強調して引き伸ばす
        if (!composites.isEmpty()) {
            double mean = composites.stream().mapToDouble(Double::doubleValue).average().orElse(70.0);
            for (RaceSpecificResult r : analyzed) {
                double stretched = mean + (r.getScore() - mean) * CONTRAST;
                stretched = Math.max(SCORE_MIN, Math.min(SCORE_MAX, stretched));
                r.setScore(Math.round(stretched * 10.0) / 10.0);
            }
        }

        // 3. スコア降順に並べ替え、順位を振り直す（未分析馬は末尾）
        analyzed.sort((a, b) -> Double.compare(b.getScore(), a.getScore()));
        List<RaceSpecificResult> results = new ArrayList<>();
        results.addAll(analyzed);
        results.addAll(unanalyzed);
        int rank = 1;
        for (RaceSpecificResult r : results) {
            r.setRankPosition(rank++);
        }
        return results;
    }

    /**
     * face_comment（「phrase1。phrase2。総括」形式）を
     * テンプレートの見出し分割（全角スペース区切り）に合わせて変換する。
     * 先頭の「。」を全角スペースに置換し、1文目を見出し、残りを本文にする。
     */
    private static String toHeadlineFormat(String comment) {
        if (comment == null || comment.isBlank()) return null;
        return comment.replaceFirst("。", "　");
    }
}
