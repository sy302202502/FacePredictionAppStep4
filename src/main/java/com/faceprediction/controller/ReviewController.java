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
import com.faceprediction.service.SnapshotService;

/**
 * レース後の答え合わせ。
 * /predict-v2 と同じ鬼眼スコア順位（◎○▲…）と、実際の着順（race_specific_accuracy）を並べる。
 * 着順・払戻は result_auto_fetcher.py が記録したもの、印は SnapshotService の固定保存を使う。
 */
@Controller
@RequestMapping("/review")
public class ReviewController {

    /** 一覧・集計の対象にする直近レース数 */
    private static final int RECENT_RACES = 30;

    @Autowired private JdbcTemplate    jdbc;
    @Autowired private BettingService  bettingService;
    @Autowired private SnapshotService snapshotService;
    @Autowired private com.faceprediction.service.RaceDiagramService diagramService;

    @GetMapping
    public String show(@RequestParam(required = false) String raceId, Model model) {

        // 結果記録済みの直近レース（開催単位）
        List<Map<String, Object>> races = jdbc.queryForList(
            "SELECT rsa.race_id, MIN(re.race_name) AS race_name, MAX(re.race_date) AS race_date " +
            "FROM race_specific_accuracy rsa " +
            "JOIN race_entry re ON re.race_id = rsa.race_id " +
            "WHERE rsa.data_source = 'stats' AND rsa.race_id IS NOT NULL " +
            "GROUP BY rsa.race_id " +
            "ORDER BY MAX(re.race_date) DESC, rsa.race_id DESC " +
            "LIMIT " + RECENT_RACES);

        List<RaceReview> reviews = new ArrayList<>();
        for (Map<String, Object> race : races) {
            String id = (String) race.get("race_id");
            // 印は固定保存（結果記録時点で確定）を使う。後の再予想・ロジック変更の影響を受けない
            List<RaceSpecificResult> ranked = snapshotService.rankedFor(id);
            // 顔面分析が1頭も無いレースは鬼眼予想を出していないので対象外
            if (ranked.isEmpty() || ranked.get(0).getScore() == null) continue;
            reviews.add(new RaceReview(
                id,
                (String) race.get("race_name"),
                String.valueOf(race.get("race_date")),
                ranked,
                bettingService.suggest(ranked, snapshotService.payoutsFor(id))));
        }
        model.addAttribute("reviews", reviews);

        RaceReview selected = reviews.stream()
            .filter(r -> r.getRaceId().equals(raceId))
            .findFirst()
            .orElse(reviews.isEmpty() ? null : reviews.get(0));
        model.addAttribute("selected", selected);
        if (selected != null) {
            model.addAttribute("betPoints", bettingService.totalPoints(selected.getBets()));
            model.addAttribute("tenkai", loadTenkaiCheck(selected.getRaceId()));
        }
        model.addAttribute("tenkaiSummary", tenkaiSummary());

        model.addAttribute("summary", summarize(reviews));
        return "prediction/review";
    }

    /**
     * 展開想定図の答え合わせ（tenkai_check.py が保存）。想定図と実際の隊列を同じ形で描けるようにする。
     * 図の無いレース・未チェック・テーブル未作成なら null。
     */
    private Map<String, Object> loadTenkaiCheck(String raceId) {
        try {
            List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT tc.pace_pred, tc.pace_actual, tc.front3f, tc.back3f, tc.front_m, tc.start_top4, tc.stretch_top4, " +
                "       tc.actual, rc.diagram " +
                "FROM tenkai_check tc JOIN race_column rc ON rc.race_id = tc.race_id WHERE tc.race_id = ?", raceId);
            if (rows.isEmpty()) return null;
            Map<String, Object> r = new LinkedHashMap<>(rows.get(0));
            List<Map<String, Object>> predicted = diagramService.scenes((String) r.get("diagram"));
            List<Map<String, Object>> actual = null;
            try {
                com.fasterxml.jackson.databind.JsonNode a =
                    new com.fasterxml.jackson.databind.ObjectMapper().readTree((String) r.get("actual"));
                actual = diagramService.scenes(a.path("diagram").toString());
            } catch (Exception ignore) { }
            if (predicted == null || actual == null || predicted.size() != actual.size()) return null;
            // 図1・図2 それぞれ「想定」と「実際」を並べる
            List<Map<String, Object>> pairs = new ArrayList<>();
            for (int i = 0; i < predicted.size(); i++) {
                Map<String, Object> p = new LinkedHashMap<>();
                p.put("predicted", predicted.get(i));
                p.put("actual", actual.get(i));
                p.put("hits", i == 0 ? r.get("start_top4") : r.get("stretch_top4"));
                p.put("hitLabel", i == 0 ? "図1で前の4頭のうち、実際に最初のコーナーを4番手以内で回った馬"
                                         : "図2で前の4頭のうち、実際に4着以内だった馬");
                pairs.add(p);
            }
            r.put("pairs", pairs);
            r.put("paceHit", r.get("pace_pred") != null && r.get("pace_pred").equals(r.get("pace_actual")));
            return r;
        } catch (Exception e) {
            return null;   // tenkai_check 未作成（まだ一度も答え合わせしていない環境）
        }
    }

    /** 展開図の答え合わせの通算（レース数・前4頭の平均的中・ペース的中率）。無ければ null */
    private Map<String, Object> tenkaiSummary() {
        try {
            Map<String, Object> m = jdbc.queryForMap(
                "SELECT COUNT(*) AS races, AVG(start_top4) AS start_top4, AVG(stretch_top4) AS stretch_top4, " +
                "       AVG(CASE WHEN pace_pred = pace_actual THEN 1.0 ELSE 0.0 END) AS pace_hit " +
                "FROM tenkai_check WHERE start_top4 IS NOT NULL");
            if (((Number) m.get("races")).intValue() == 0) return null;
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("races", ((Number) m.get("races")).intValue());
            out.put("startTop4", String.format("%.1f", ((Number) m.get("start_top4")).doubleValue()));
            out.put("stretchTop4", String.format("%.1f", ((Number) m.get("stretch_top4")).doubleValue()));
            out.put("paceHit", Math.round(((Number) m.get("pace_hit")).doubleValue() * 100));
            return out;
        } catch (Exception e) {
            return null;
        }
    }

    /**
     * 1レースの答え合わせ要約（JSON）。Discord 通知（result_auto_fetcher.py）が使う。
     * 画面と同じ固定保存・払戻表・買い目で判定するので、通知と画面の結果が食い違わない。
     */
    @GetMapping("/api")
    @org.springframework.web.bind.annotation.ResponseBody
    public Map<String, Object> api(@RequestParam String raceId) {
        Map<String, Object> out = new LinkedHashMap<>();
        // 公開範囲は /review 画面と同じ（結果記録済みの直近レース）。形式外の ID や範囲外は返さない
        if (!raceId.matches("\\d{12}")) {
            out.put("available", false);
            return out;
        }
        Integer inRange = jdbc.queryForObject(
            "SELECT COUNT(*) FROM (" +
            "  SELECT rsa.race_id FROM race_specific_accuracy rsa " +
            "  JOIN race_entry re ON re.race_id = rsa.race_id " +
            "  WHERE rsa.data_source = 'stats' AND rsa.race_id IS NOT NULL " +
            "  GROUP BY rsa.race_id ORDER BY MAX(re.race_date) DESC, rsa.race_id DESC " +
            "  LIMIT " + RECENT_RACES + ") t WHERE t.race_id = ?",
            Integer.class, raceId);
        if (inRange == null || inRange == 0) {
            out.put("available", false);
            return out;
        }
        List<Map<String, Object>> race = jdbc.queryForList(
            "SELECT MIN(race_name) AS race_name, MAX(race_date) AS race_date FROM race_entry WHERE race_id = ?",
            raceId);
        List<RaceSpecificResult> ranked = snapshotService.rankedFor(raceId);
        if (race.isEmpty() || race.get(0).get("race_name") == null
                || ranked.isEmpty() || ranked.get(0).getScore() == null) {
            out.put("available", false);
            return out;
        }
        RaceReview r = new RaceReview(raceId, (String) race.get(0).get("race_name"),
            String.valueOf(race.get(0).get("race_date")), ranked,
            bettingService.suggest(ranked, snapshotService.payoutsFor(raceId)));
        RaceSpecificResult h = r.getHonmei();
        out.put("available", true);
        out.put("raceId", raceId);
        out.put("raceName", r.getRaceName());
        out.put("raceDate", r.getRaceDate());
        out.put("honmeiName", h.getHorseName());
        out.put("honmeiNumber", h.getHorseNumber());
        out.put("honmeiRank", h.getActualRank());
        out.put("settled", !r.getBets().isEmpty() && r.getBets().get(0).getHit() != null);
        out.put("hitTypes", r.getHitTypes());
        out.put("payoutKnown", r.isPayoutKnown());
        out.put("returnTotal", r.getReturnTotal());
        out.put("invested", r.getInvested());
        return out;
    }

    /** 直近レース全体での ◎の成績と券種別の的中レース数 */
    private Map<String, Object> summarize(List<RaceReview> reviews) {
        int honmeiWin = 0;
        int honmeiPlace = 0;
        Map<String, Integer> betHits = new LinkedHashMap<>();
        int betRaces = 0;
        // 回収率: 払戻表で判定できたレースだけで計算（投資 = 点数×100円）
        int payoutRaces = 0;
        long invested = 0;
        long returned = 0;
        Map<String, long[]> byType = new LinkedHashMap<>();  // 券種 → {投資, 払戻}
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
            if (r.isPayoutKnown()) {
                payoutRaces++;
                for (BetLine line : r.getBets()) {
                    long in = line.getPoints() * 100L;
                    long out = line.getReturnAmount();
                    invested += in;
                    returned += out;
                    long[] t = byType.computeIfAbsent(line.getType(), k -> new long[2]);
                    t[0] += in;
                    t[1] += out;
                }
            }
        }
        Map<String, Long> recoveryByType = new LinkedHashMap<>();
        for (Map.Entry<String, long[]> e : byType.entrySet()) {
            recoveryByType.put(e.getKey(), e.getValue()[0] > 0 ? Math.round(e.getValue()[1] * 100.0 / e.getValue()[0]) : 0L);
        }
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("races", reviews.size());
        s.put("honmeiWin", honmeiWin);
        s.put("honmeiPlace", honmeiPlace);
        s.put("betRaces", betRaces);
        s.put("betHits", betHits);
        s.put("payoutRaces", payoutRaces);
        s.put("invested", invested);
        s.put("returned", returned);
        s.put("recovery", invested > 0 ? Math.round(returned * 100.0 / invested) : 0L);
        s.put("recoveryByType", recoveryByType);
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

        /** 全券種が払戻表で判定できたか（回収率の計算対象か） */
        public boolean isPayoutKnown() {
            return !bets.isEmpty() && bets.stream().allMatch(b -> b.getReturnAmount() != null
                && b.getCombos().stream().allMatch(c -> c.getHit() != null));
        }

        /** 払戻合計（100円×全組）。払戻表で判定できていなければ null */
        public Integer getReturnTotal() {
            return isPayoutKnown() ? bets.stream().mapToInt(BetLine::getReturnAmount).sum() : null;
        }

        /** 投資額（点数×100円） */
        public int getInvested() {
            return bets.stream().mapToInt(BetLine::getPoints).sum() * 100;
        }

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
