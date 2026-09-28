package com.faceprediction.controller;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import com.faceprediction.entity.RaceSpecificResult;
import com.faceprediction.service.BetLine;
import com.faceprediction.service.BettingService;
import com.faceprediction.service.FaceRankingService;

/**
 * レース後の答え合わせ。
 * /predict-v2 と同じ鬼眼スコア順位（◎○▲…）と、実際の着順（race_specific_accuracy）を並べる。
 * 着順は result_auto_fetcher.py が data_source='stats' で記録したものを使う。
 */
@Controller
@RequestMapping("/review")
public class ReviewController {

    /** 一覧・集計の対象にする直近レース数 */
    private static final int RECENT_RACES = 30;

    @Autowired private JdbcTemplate       jdbc;
    @Autowired private FaceRankingService rankingService;
    @Autowired private BettingService     bettingService;

    @GetMapping
    public String show(@RequestParam(required = false) String raceId, Model model) {

        // 結果記録済みの直近レースについて、予想と着順をまとめて取得する。
        // 開催は race_id、予想と出走表は horse_id で突合（同名別年の混入を防ぐ）。
        // 着順(race_specific_accuracy)は result_auto_fetcher が stats_prediction の馬名を
        // そのまま写して保存している（着順自体は horse_id で突合済み）ので horse_name で結べる
        List<Map<String, Object>> rows = jdbc.queryForList(
            "WITH recorded AS ( " +
            "  SELECT rsa.race_id, MAX(re.race_date) AS race_date " +
            "  FROM race_specific_accuracy rsa " +
            "  JOIN race_entry re ON re.race_id = rsa.race_id " +
            "  WHERE rsa.data_source = 'stats' AND rsa.race_id IS NOT NULL " +
            "  GROUP BY rsa.race_id " +
            "  ORDER BY MAX(re.race_date) DESC, rsa.race_id DESC " +
            "  LIMIT " + RECENT_RACES + " ) " +
            "SELECT sp.race_id, re.race_name, rc.race_date, " +
            "       sp.horse_name, sp.image_path, sp.face_comment, sp.face_score, sp.score, " +
            "       re.horse_number, re.post_position, rsa.actual_rank " +
            "FROM recorded rc " +
            "JOIN stats_prediction sp ON sp.race_id = rc.race_id " +
            "JOIN race_entry re ON re.race_id = sp.race_id AND re.horse_id = sp.horse_id " +
            "LEFT JOIN race_specific_accuracy rsa " +
            "  ON rsa.race_id = sp.race_id AND rsa.data_source = 'stats' " +
            " AND rsa.horse_name = sp.horse_name " +
            "ORDER BY rc.race_date DESC, sp.race_id DESC");

        Map<String, List<Map<String, Object>>> byRace = new LinkedHashMap<>();
        for (Map<String, Object> row : rows) {
            byRace.computeIfAbsent((String) row.get("race_id"), k -> new ArrayList<>()).add(row);
        }

        List<RaceReview> reviews = new ArrayList<>();
        for (List<Map<String, Object>> raceRows : byRace.values()) {
            Map<String, Object> first = raceRows.get(0);
            List<RaceSpecificResult> ranked = rankingService.rank(raceRows);
            // 顔面分析が1頭も無いレースは鬼眼予想を出していないので対象外
            if (ranked.isEmpty() || ranked.get(0).getScore() == null) continue;
            reviews.add(new RaceReview(
                (String) first.get("race_id"),
                (String) first.get("race_name"),
                String.valueOf(first.get("race_date")),
                ranked,
                bettingService.suggest(ranked)));
        }
        model.addAttribute("reviews", reviews);

        RaceReview selected = reviews.stream()
            .filter(r -> r.getRaceId().equals(raceId))
            .findFirst()
            .orElse(reviews.isEmpty() ? null : reviews.get(0));
        model.addAttribute("selected", selected);
        if (selected != null) {
            model.addAttribute("betPoints", bettingService.totalPoints(selected.getBets()));
        }

        model.addAttribute("summary", summarize(reviews));
        return "prediction/review";
    }

    /** 直近レース全体での ◎の成績と券種別の的中レース数 */
    private Map<String, Object> summarize(List<RaceReview> reviews) {
        int honmeiWin = 0;
        int honmeiPlace = 0;
        Map<String, Integer> betHits = new LinkedHashMap<>();
        int betRaces = 0;
        for (RaceReview r : reviews) {
            Integer rank = r.getHonmei().getActualRank();
            if (rank != null && rank == 1) honmeiWin++;
            if (rank != null && rank <= 3) honmeiPlace++;
            // 1〜3着がそろっていない（判定保留の）レースは券種の集計に入れない
            if (r.getBets().isEmpty() || r.getBets().get(0).getHit() == null) continue;
            betRaces++;
            for (BetLine line : r.getBets()) {
                betHits.merge(line.getType(), Boolean.TRUE.equals(line.getHit()) ? 1 : 0, Integer::sum);
            }
        }
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("races", reviews.size());
        s.put("honmeiWin", honmeiWin);
        s.put("honmeiPlace", honmeiPlace);
        s.put("betRaces", betRaces);
        s.put("betHits", betHits);
        return s;
    }

    /** 1レース分の答え合わせ */
    public static class RaceReview {
        private final String raceId;
        private final String raceName;
        private final String raceDate;
        private final List<RaceSpecificResult> ranked;
        private final List<BetLine> bets;

        public RaceReview(String raceId, String raceName, String raceDate,
                          List<RaceSpecificResult> ranked, List<BetLine> bets) {
            this.raceId = raceId;
            this.raceName = raceName;
            this.raceDate = raceDate;
            this.ranked = ranked;
            this.bets = bets;
        }

        public String getRaceId() { return raceId; }
        public String getRaceName() { return raceName; }
        public String getRaceDate() { return raceDate; }
        public List<RaceSpecificResult> getRanked() { return ranked; }
        public List<BetLine> getBets() { return bets; }

        /** ◎（鬼眼スコア1位） */
        public RaceSpecificResult getHonmei() { return ranked.get(0); }

        /** 的中した券種名（例: 複勝・ワイド） */
        public List<String> getHitTypes() {
            List<String> types = new ArrayList<>();
            for (BetLine line : bets) {
                if (Boolean.TRUE.equals(line.getHit())) types.add(line.getType());
            }
            return types;
        }

        /** 実際の1〜3着（着順昇順）。印は鬼眼順位のもの */
        public List<RaceSpecificResult> getPodium() {
            List<RaceSpecificResult> podium = new ArrayList<>();
            for (RaceSpecificResult r : ranked) {
                if (r.getActualRank() != null && r.getActualRank() <= 3) podium.add(r);
            }
            podium.sort((a, b) -> Integer.compare(a.getActualRank(), b.getActualRank()));
            return podium;
        }

        public String markOf(Integer rank) { return FaceRankingService.markOf(rank); }
    }
}
