package com.faceprediction.service;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.function.Predicate;
import java.util.stream.Collectors;

import org.springframework.stereotype.Service;

import com.faceprediction.entity.RaceSpecificResult;

/**
 * 鬼眼スコア上位5頭（◎○▲△注）から買い目を組み立てる。
 * 各券種 100円 × 点数で、合計 20点（2,000円）の構成:
 *   単勝 ◎ / 複勝 ◎ / ワイド ◎-○▲ / 馬連 ◎-○▲△注
 *   三連複 ◎軸1頭流し ○▲△注 / 三連単 ◎→○▲→○▲△注
 * レース後は netkeiba の払戻表（race_payout）に照らして的中と払戻を判定する。
 * 払戻表は同着・複勝の頭数条件・発売なしをすべて反映しているため最も正確。
 * 払戻が無い（未取得・馬番未確定）場合だけ着順（actualRank）から判定する。
 */
@Service
public class BettingService {

    /** 買い目を組むのに必要な顔面分析済みの頭数（◎〜注） */
    private static final int PICK_COUNT = 5;
    /** 複勝が2着までになる出走頭数の上限（JRA: 7頭以下は2着まで） */
    private static final int SMALL_FIELD = 7;

    public List<BetLine> suggest(List<RaceSpecificResult> ranked) {
        return suggest(ranked, Map.of());
    }

    /**
     * @param payouts 払戻表。キーは payoutKey(券種, 馬番...)、値は100円あたりの払戻額
     */
    public List<BetLine> suggest(List<RaceSpecificResult> ranked, Map<String, Integer> payouts) {
        List<RaceSpecificResult> picks = ranked.stream()
            .filter(r -> r.getScore() != null)
            .limit(PICK_COUNT)
            .collect(Collectors.toList());
        if (picks.size() < PICK_COUNT) return List.of();

        // 払戻表で判定できるのは、払戻があり、買い目の5頭すべてに馬番があるとき
        boolean usePayout = payouts != null && !payouts.isEmpty()
            && picks.stream().allMatch(r -> r.getHorseNumber() != null);

        // 結果確定の判定: 1〜3着に当たる着順がそろっていること（1着だけ取れた半端な状態で
        // ワイドや三連系を「外れ」と確定させない）。同着なら 1,1,3 のように並ぶ
        List<Integer> podiumRanks = ranked.stream()
            .map(RaceSpecificResult::getActualRank)
            .filter(r -> r != null && r <= 3)
            .sorted()
            .collect(Collectors.toList());
        boolean settled = usePayout || (podiumRanks.size() >= 3 && podiumRanks.get(0) == 1);
        Map<String, Integer> pay = usePayout ? payouts : null;
        // 三連単の正解の着順列（同着時は 1,1,3 など。3着同着でも先頭3つで判定できる）
        List<Integer> trifectaRanks = settled ? podiumRanks.subList(0, 3) : List.of();
        long starters = ranked.stream().filter(r -> r.getActualRank() != null).count();
        int placeLimit = starters > 0 && starters <= SMALL_FIELD ? 2 : 3;

        List<BetLine> lines = new ArrayList<>();

        BetLine win = new BetLine("単勝", "◎ 1点");
        addCombo(win, picks, settled, pay, "", c -> within(c[0], 1), 0);
        lines.add(win);

        BetLine place = new BetLine("複勝", "◎ 1点");
        addCombo(place, picks, settled, pay, "", c -> within(c[0], placeLimit), 0);
        lines.add(place);

        BetLine wide = new BetLine("ワイド", "◎-○▲ 2点");
        for (int k = 1; k <= 2; k++) {
            addCombo(wide, picks, settled, pay, " - ", c -> within(c[0], 3) && within(c[1], 3), 0, k);
        }
        lines.add(wide);

        BetLine quinella = new BetLine("馬連", "◎-○▲△注 流し 4点");
        for (int k = 1; k <= 4; k++) {
            addCombo(quinella, picks, settled, pay, " - ", c -> within(c[0], 2) && within(c[1], 2), 0, k);
        }
        lines.add(quinella);

        BetLine trio = new BetLine("三連複", "◎軸1頭流し ○▲△注 6点");
        for (int a = 1; a <= 4; a++) {
            for (int b = a + 1; b <= 4; b++) {
                addCombo(trio, picks, settled, pay, " - ",
                         c -> within(c[0], 3) && within(c[1], 3) && within(c[2], 3), 0, a, b);
            }
        }
        lines.add(trio);

        BetLine trifecta = new BetLine("三連単", "◎→○▲→○▲△注 6点");
        for (int a = 1; a <= 2; a++) {
            for (int b = 1; b <= 4; b++) {
                if (b == a) continue;
                // 着順列が正解と一致すれば的中。同着(1着同着なら A→B→C と B→A→C の両方)にも対応
                addCombo(trifecta, picks, settled, pay, " → ",
                         c -> trifectaRanks.equals(Arrays.asList(
                                  c[0].getActualRank(), c[1].getActualRank(), c[2].getActualRank())),
                         0, a, b);
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
                          Map<String, Integer> payouts,
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

        if (payouts != null) {
            int[] nums = Arrays.stream(horses).mapToInt(RaceSpecificResult::getHorseNumber).toArray();
            Integer pay = payouts.get(payoutKey(line.getType(), nums));
            line.addCombo(new BetLine.Combo(label, pay != null, pay));
        } else {
            line.addCombo(new BetLine.Combo(label, settled ? isHit.test(horses) : null, null));
        }
    }

    /**
     * 払戻表のキー「券種:馬番-馬番…」。result_auto_fetcher.payout_key と同じ規則で、
     * 順序に意味がある馬単・三連単以外は馬番を昇順に並べる。
     */
    public static String payoutKey(String betType, int... numbers) {
        int[] nums = numbers.clone();
        if (!"馬単".equals(betType) && !"三連単".equals(betType)) Arrays.sort(nums);
        return betType + ":" + Arrays.stream(nums).mapToObj(String::valueOf).collect(Collectors.joining("-"));
    }

    /** 「◎3」のように印＋馬番。馬番未確定（枠順発表前）は印だけ */
    private static String labelOf(RaceSpecificResult r) {
        String mark = FaceRankingService.markOf(r.getRankPosition());
        return r.getHorseNumber() != null ? mark + r.getHorseNumber() : mark;
    }

    private static boolean within(RaceSpecificResult r, int rank) {
        return r.getActualRank() != null && r.getActualRank() <= rank;
    }

}
