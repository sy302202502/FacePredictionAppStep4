package com.faceprediction.controller;

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
import com.faceprediction.service.BetLine;
import com.faceprediction.service.BettingService;
import com.faceprediction.service.FaceRankingService;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

@Controller
@RequestMapping("/predict-v2")
public class RacePredictionV2Controller {

    private static final Logger log = LoggerFactory.getLogger(RacePredictionV2Controller.class);

    @Autowired private RaceOddsRepository oddsRepo;
    @Autowired private JdbcTemplate       jdbc;
    @Autowired private FaceRankingService rankingService;
    @Autowired private BettingService     bettingService;

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
            // race_entry の最新 horse_number を表示用に取得
            List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT sp.horse_name, sp.image_path, sp.face_comment, sp.face_score, sp.score, sp.rank_position, " +
                "       re.horse_number, re.post_position " +
                "FROM stats_prediction sp " +
                // 馬は ID で厳密突合。開催は「この race_name の最新開催」に固定し、
                // 予想行側は race_id 一致 or 未付与(旧コード由来のNULL)を許容する
                "INNER JOIN race_entry re " +
                "  ON re.horse_id = sp.horse_id " +
                " AND re.race_id = (SELECT race_id FROM race_entry WHERE race_name = sp.race_name " +
                "                   ORDER BY race_date DESC, race_id DESC LIMIT 1) " +
                "WHERE sp.race_name = ? " +
                "  AND (sp.race_id = re.race_id " +
                // 旧コード由来の race_id NULL 行は、同じ馬の最新開催の行が無いときだけ使う
                // （両方あると同じ馬が二重に表示されていた）
                "       OR (sp.race_id IS NULL AND NOT EXISTS (SELECT 1 FROM stats_prediction sp2 " +
                "           WHERE sp2.race_id = re.race_id AND sp2.horse_id = sp.horse_id))) " +
                "ORDER BY sp.rank_position ASC",
                selected);

            // 防御的検知: stats_prediction には予想があるのに JOIN 結果ゼロ件
            // → race_entry が同期失敗等で空になっている兆候を即時検知
            if (rows.isEmpty()) {
                Integer rawCount = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM stats_prediction WHERE race_name = ?",
                    Integer.class, selected);
                if (rawCount != null && rawCount > 0) {
                    log.warn("RACE_ENTRY MISMATCH: race={} has {} predictions but JOIN returned 0 rows. " +
                             "Check race_entry sync status.", selected, rawCount);
                }
            }

            List<RaceSpecificResult> results = rankingService.rank(rows);
            model.addAttribute("results", results);
            // 枠順確定前（特別登録の段階）は馬番が無く、18頭を超える登録馬が並ぶこともある。
            // 確定メンバーはレース前日の出馬表同期で反映される
            boolean entriesFinal = !results.isEmpty()
                && results.stream().allMatch(r -> r.getHorseNumber() != null);
            model.addAttribute("entriesFinal", entriesFinal);

            // 買い目提案（◎〜注の5頭が顔面分析済みのときだけ）
            List<BetLine> bets = bettingService.suggest(results);
            model.addAttribute("bets", bets);
            model.addAttribute("betPoints", bettingService.totalPoints(bets));

            // 表示中の開催（この race_name の最新開催）
            List<String> latestIds = jdbc.queryForList(
                "SELECT race_id FROM race_entry WHERE race_name = ? " +
                "ORDER BY race_date DESC, race_id DESC LIMIT 1",
                String.class, selected);
            String latestRaceId = latestIds.isEmpty() ? null : latestIds.get(0);

            // 結果が記録済みなら答え合わせページへの導線を出す
            Integer recorded = latestRaceId == null ? 0 : jdbc.queryForObject(
                "SELECT COUNT(*) FROM race_specific_accuracy " +
                "WHERE data_source = 'stats' AND race_id = ?",
                Integer.class, latestRaceId);
            model.addAttribute("reviewRaceId", recorded != null && recorded > 0 ? latestRaceId : null);

            // オッズデータ（馬名→RaceOdds）。レース当日以外は空マップになる。
            // race_name で引くと前年の同名重賞のオッズが混ざるため、開催(race_id)で限定する
            List<RaceOdds> oddsList = latestRaceId == null ? List.of()
                : oddsRepo.findByRaceIdOrderByPopularityAsc(latestRaceId);
            Map<String, RaceOdds> oddsMap = oddsList.stream()
                .collect(Collectors.toMap(RaceOdds::getHorseName, o -> o, (a, b) -> a));
            model.addAttribute("oddsMap", oddsMap);
        } else {
            model.addAttribute("results", List.of());
            model.addAttribute("oddsMap", Map.of());
            model.addAttribute("bets", List.of());
        }

        return "prediction/v2";
    }
}
