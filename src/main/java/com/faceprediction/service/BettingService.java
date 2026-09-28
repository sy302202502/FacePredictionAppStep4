package com.faceprediction.service;

import java.util.ArrayList;
import java.util.List;
import java.util.function.Predicate;
import java.util.stream.Collectors;

import org.springframework.stereotype.Service;

import com.faceprediction.entity.RaceSpecificResult;

/**
 * 鬼眼スコア上位5頭（◎○▲△注）から買い目を組み立てる。
 * 各券種 100円 × 点数で、合計 20点（2,000円）の構成:
 *   単勝 ◎ / 複勝 ◎ / ワイド ◎-○▲ / 馬連 ◎-○▲△注
 *   三連複 ◎軸1頭流し ○▲△注 / 三連単 ◎→○▲→○▲△注
 * 結果（actualRank）が入っていれば各組の的中も判定する。
 */
@Service
public class BettingService {

    /** 買い目を組むのに必要な顔面分析済みの頭数（◎〜注） */
    private static final int PICK_COUNT = 5;
    /** 複勝が2着までになる出走頭数の上限（JRA: 7頭以下は2着まで） */
    private static final int SMALL_FIELD = 7;

    public List<BetLine> suggest(List<RaceSpecificResult> ranked) {
        List<RaceSpecificResult> picks = ranked.stream()
            .filter(r -> r.getScore() != null)
            .limit(PICK_COUNT)
            .collect(Collectors.toList());
        if (picks.size() < PICK_COUNT) return List.of();

        boolean settled = ranked.stream().anyMatch(r -> Integer.valueOf(1).equals(r.getActualRank()));
        long starters = ranked.stream().filter(r -> r.getActualRank() != null).count();
        int placeLimit = starters > 0 && starters <= SMALL_FIELD ? 2 : 3;

        List<BetLine> lines = new ArrayList<>();

        BetLine win = new BetLine("単勝", "◎ 1点");
        addCombo(win, picks, settled, "", c -> within(c[0], 1), 0);
        lines.add(win);

        BetLine place = new BetLine("複勝", "◎ 1点");
        addCombo(place, picks, settled, "", c -> within(c[0], placeLimit), 0);
        lines.add(place);

        BetLine wide = new BetLine("ワイド", "◎-○▲ 2点");
        for (int k = 1; k <= 2; k++) {
            addCombo(wide, picks, settled, " - ", c -> within(c[0], 3) && within(c[1], 3), 0, k);
        }
        lines.add(wide);

        BetLine quinella = new BetLine("馬連", "◎-○▲△注 流し 4点");
        for (int k = 1; k <= 4; k++) {
            addCombo(quinella, picks, settled, " - ", c -> within(c[0], 2) && within(c[1], 2), 0, k);
        }
        lines.add(quinella);

        BetLine trio = new BetLine("三連複", "◎軸1頭流し ○▲△注 6点");
        for (int a = 1; a <= 4; a++) {
            for (int b = a + 1; b <= 4; b++) {
                addCombo(trio, picks, settled, " - ",
                         c -> within(c[0], 3) && within(c[1], 3) && within(c[2], 3), 0, a, b);
            }
        }
        lines.add(trio);

        BetLine trifecta = new BetLine("三連単", "◎→○▲→○▲△注 6点");
        for (int a = 1; a <= 2; a++) {
            for (int b = 1; b <= 4; b++) {
                if (b == a) continue;
                addCombo(trifecta, picks, settled, " → ",
                         c -> exactly(c[0], 1) && exactly(c[1], 2) && exactly(c[2], 3), 0, a, b);
            }
        }
        lines.add(trifecta);

        return lines;
    }

    /** 全券種の合計点数 */
    public int totalPoints(List<BetLine> lines) {
        return lines.stream().mapToInt(BetLine::getPoints).sum();
    }

    private void addCombo(BetLine line, List<RaceSpecificResult> picks, boolean settled,
                          String sep, Predicate<RaceSpecificResult[]> isHit, int... idx) {
        RaceSpecificResult[] horses = new RaceSpecificResult[idx.length];
        List<String> parts = new ArrayList<>();
        for (int i = 0; i < idx.length; i++) {
            horses[i] = picks.get(idx[i]);
            parts.add(labelOf(horses[i]));
        }
        // 単勝・複勝のように1頭だけの買い目は馬名まで出す
        String label = String.join(sep, parts);
        if (idx.length == 1) label += " " + horses[0].getHorseName();
        line.addCombo(new BetLine.Combo(label, settled ? isHit.test(horses) : null));
    }

    /** 「◎3」のように印＋馬番。馬番未確定（枠順発表前）は印だけ */
    private static String labelOf(RaceSpecificResult r) {
        String mark = FaceRankingService.markOf(r.getRankPosition());
        return r.getHorseNumber() != null ? mark + r.getHorseNumber() : mark;
    }

    private static boolean within(RaceSpecificResult r, int rank) {
        return r.getActualRank() != null && r.getActualRank() <= rank;
    }

    private static boolean exactly(RaceSpecificResult r, int rank) {
        return r.getActualRank() != null && r.getActualRank() == rank;
    }
}
