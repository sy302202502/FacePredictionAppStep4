package com.faceprediction.controller;

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
import com.faceprediction.service.RaceSelectionService;
import com.faceprediction.service.SnapshotService;

/**
 * 配信用オーバーレイ（OBS のブラウザソースに貼る。1920×1080 想定）。
 *   /overlay?raceId=…            … 予想（◎○▲△注・顔写真・買い目）。結果が記録されると自動で結果表示に切り替わる
 *   &bg=dark                     … 黒背景（既定は透明で配信画面に重ねられる）
 *   &mode=pick / mode=result     … 表示の固定（既定は自動）
 * 公開ページ（/predict-v2・/review）と同じ内容だけを表示する。1分ごとに自動更新。
 */
@Controller
@RequestMapping("/overlay")
public class OverlayController {

    @Autowired private JdbcTemplate         jdbc;
    @Autowired private RaceSelectionService selectionService;
    @Autowired private FaceRankingService   rankingService;
    @Autowired private BettingService       bettingService;
    @Autowired private SnapshotService      snapshotService;

    @GetMapping
    public String show(@RequestParam(required = false) String raceId,
                       @RequestParam(required = false) String raceName,
                       @RequestParam(required = false, defaultValue = "") String bg,
                       @RequestParam(required = false, defaultValue = "auto") String mode,
                       Model model) {
        // 毎分再読み込みされるので、全開催の一覧は作らず対象の1開催だけ引く
        Map<String, Object> race = selectionService.resolveOne(raceId, raceName);
        model.addAttribute("bgDark", "dark".equals(bg));
        if (race == null) {
            model.addAttribute("empty", "予想のあるレースがありません");
            return "overlay/index";
        }
        String id = (String) race.get("race_id");
        String name = (String) race.get("race_name");
        model.addAttribute("raceId", id);
        model.addAttribute("raceName", name);

        Integer recorded = jdbc.queryForObject(
            "SELECT COUNT(*) FROM race_specific_accuracy WHERE data_source = 'stats' AND race_id = ?",
            Integer.class, id);
        boolean showResult = "result".equals(mode) || ("auto".equals(mode) && recorded != null && recorded > 0);

        List<RaceSpecificResult> ranked;
        List<BetLine> bets;
        if (showResult) {
            ranked = snapshotService.rankedFor(id);
            bets = bettingService.suggest(ranked, snapshotService.payoutsFor(id));
        } else {
            ranked = rankingService.rank(jdbc.queryForList(
                "SELECT sp.horse_id, sp.horse_name, sp.image_path, sp.face_comment, sp.face_score, sp.score, " +
                "       re.horse_number, re.post_position " +
                "FROM stats_prediction sp JOIN race_entry re ON re.race_id = sp.race_id AND re.horse_id = sp.horse_id " +
                "WHERE sp.race_id = ?", id));
            bets = bettingService.suggest(ranked);
        }
        List<RaceSpecificResult> picks = ranked.stream().filter(r -> r.getScore() != null).limit(5)
            .collect(java.util.stream.Collectors.toList());
        if (picks.isEmpty()) {
            // 顔面分析が済んでいない（または予想データが欠けた）レース。◎が無いので表示しない
            model.addAttribute("empty", "このレースの鬼眼予想はまだありません");
            return "overlay/index";
        }
        // 写真は結果表示（固定保存）でも出したいので、馬ID から候補写真のパスを補う
        for (RaceSpecificResult r : picks) {
            if (r.getImagePath() == null && r.getHorseId() != null) {
                r.setImagePath("/uploads/candidates/" + r.getHorseId() + ".jpg");
            }
        }
        model.addAttribute("showResult", showResult);
        model.addAttribute("picks", picks);
        model.addAttribute("bets", bets);
        model.addAttribute("betPoints", bettingService.totalPoints(bets));
        if (showResult) {
            ReviewController.RaceReview review = new ReviewController.RaceReview(id, name, "", ranked, bets);
            model.addAttribute("review", review);
        }
        return "overlay/index";
    }
}
