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
            // 顔面スコア順に並べ、上位から順位を振り直す（顔面予想ページのため）
            List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT horse_name, image_path, face_comment, face_score " +
                "FROM stats_prediction WHERE race_name = ? " +
                "ORDER BY face_score DESC NULLS LAST, rank_position ASC",
                selected);

            List<RaceSpecificResult> results = new ArrayList<>();
            int rank = 1;
            for (Map<String, Object> row : rows) {
                RaceSpecificResult r = new RaceSpecificResult();
                r.setHorseName((String) row.get("horse_name"));
                r.setImagePath((String) row.get("image_path"));
                r.setComment(toHeadlineFormat((String) row.get("face_comment")));
                Object fs = row.get("face_score");
                r.setScore(fs != null ? ((Number) fs).doubleValue() : null);
                r.setRankPosition(rank++);
                results.add(r);
            }
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
