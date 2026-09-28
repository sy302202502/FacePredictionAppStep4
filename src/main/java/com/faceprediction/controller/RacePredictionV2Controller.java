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
                "  AND (sp.race_id = re.race_id OR sp.race_id IS NULL) " +
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

            // 買い目提案（◎〜注の5頭が顔面分析済みのときだけ）
            List<BetLine> bets = bettingService.suggest(results);
            model.addAttribute("bets", bets);
            model.addAttribute("betPoints", bettingService.totalPoints(bets));

            // 結果が記録済みなら答え合わせページへの導線を出す（最新開催の race_id で判定）
            List<String> reviewIds = jdbc.queryForList(
                "SELECT rsa.race_id FROM race_specific_accuracy rsa " +
                "WHERE rsa.data_source = 'stats' AND rsa.race_id = " +
                "  (SELECT race_id FROM race_entry WHERE race_name = ? " +
                "   ORDER BY race_date DESC, race_id DESC LIMIT 1) " +
                "LIMIT 1",
                String.class, selected);
            model.addAttribute("reviewRaceId", reviewIds.isEmpty() ? null : reviewIds.get(0));

            // オッズデータ（馬名→RaceOdds）。レース当日以外は空マップになる
            List<RaceOdds> oddsList = oddsRepo.findByRaceNameOrderByPopularityAsc(selected);
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
