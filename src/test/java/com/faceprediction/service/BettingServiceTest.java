package com.faceprediction.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import com.faceprediction.entity.RaceSpecificResult;

/**
 * 買い目の組み立てと的中判定のテスト。
 * 印は ◎=A ○=B ▲=C △=D 注=E（鬼眼スコア順）、F 以下は印外。
 */
class BettingServiceTest {

    private final FaceRankingService ranking = new FaceRankingService();
    private final BettingService betting = new BettingService();

    /** A〜H の8頭立て。finish は馬名→着順（null=着順なし） */
    private List<RaceSpecificResult> race(Map<String, Integer> finish) {
        String[] names = {"A", "B", "C", "D", "E", "F", "G", "H"};
        List<Map<String, Object>> rows = new ArrayList<>();
        for (int i = 0; i < names.length; i++) {
            Map<String, Object> row = new HashMap<>();
            row.put("horse_name", names[i]);
            row.put("face_score", 90.0 - i * 3);
            row.put("score", 80.0 - i * 3);
            row.put("horse_number", i + 1);
            row.put("actual_rank", finish.get(names[i]));
            rows.add(row);
        }
        return ranking.rank(rows);
    }

    private BetLine line(List<BetLine> lines, String type) {
        return lines.stream().filter(l -> l.getType().equals(type)).findFirst().orElseThrow();
    }

    @Test
    void 二十点の買い目を組む() {
        List<BetLine> lines = betting.suggest(race(Map.of()));
        assertEquals(20, betting.totalPoints(lines));
        assertEquals("◎1", line(lines, "単勝").getCombos().get(0).getLabel().split(" ")[0]);
        // 結果が無ければ判定しない
        assertNull(line(lines, "馬連").getHit());
    }

    @Test
    void 本命が勝ち相手が二三着なら全券種的中() {
        List<BetLine> lines = betting.suggest(race(Map.of("A", 1, "B", 2, "C", 3, "D", 4)));
        for (BetLine l : lines) {
            assertTrue(l.getHit(), l.getType());
        }
    }

    @Test
    void 本命二着は複勝と馬連とワイドのみ() {
        List<BetLine> lines = betting.suggest(race(Map.of("D", 1, "A", 2, "F", 3)));
        assertEquals(false, line(lines, "単勝").getHit());
        assertEquals(true, line(lines, "複勝").getHit());
        assertEquals(true, line(lines, "馬連").getHit());   // ◎-△
        assertEquals(false, line(lines, "ワイド").getHit()); // ◎-○▲ のみ購入
        assertEquals(false, line(lines, "三連複").getHit()); // 3着が印外
        assertEquals(false, line(lines, "三連単").getHit());
    }

    @Test
    void 一着同着の三連単は両方の並びが的中() {
        // A と B が1着同着、C が3着 → A→B→C も B→A→C も的中。◎軸なので A→B→C を買っている
        List<BetLine> lines = betting.suggest(race(Map.of("A", 1, "B", 1, "C", 3)));
        assertEquals(true, line(lines, "単勝").getHit());
        assertEquals(true, line(lines, "三連単").getHit());
        assertEquals(true, line(lines, "三連複").getHit());
    }

    @Test
    void 一着しか取れていなければ判定保留() {
        List<BetLine> lines = betting.suggest(race(Map.of("A", 1)));
        assertNull(line(lines, "ワイド").getHit());
        assertNull(line(lines, "単勝").getHit());
    }

    @Test
    void 七頭以下なら複勝は二着まで() {
        Map<String, Integer> finish = new HashMap<>();
        finish.put("B", 1);
        finish.put("C", 2);
        finish.put("A", 3);
        finish.put("D", 4);
        finish.put("E", 5);
        finish.put("F", 6);
        finish.put("G", 7);
        // H は取消（着順なし）→ 7頭立て
        List<BetLine> lines = betting.suggest(race(finish));
        assertEquals(false, line(lines, "複勝").getHit());
    }

    @Test
    void 同点でも印の並びは馬番順で決まる() {
        List<Map<String, Object>> rows = new ArrayList<>();
        for (int n : new int[] {5, 2, 9}) {
            Map<String, Object> row = new HashMap<>();
            row.put("horse_name", "馬" + n);
            row.put("face_score", 80.0);
            row.put("score", 70.0);
            row.put("horse_number", n);
            rows.add(row);
        }
        List<RaceSpecificResult> ranked = ranking.rank(rows);
        assertEquals(2, ranked.get(0).getHorseNumber());
        assertEquals(5, ranked.get(1).getHorseNumber());
        assertEquals(9, ranked.get(2).getHorseNumber());
    }
}
