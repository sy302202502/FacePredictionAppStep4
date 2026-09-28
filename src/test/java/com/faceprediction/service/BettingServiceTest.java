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

    @Test
    void 払戻表があれば払戻表で判定し払戻額を合計する() {
        // A(1番)が1着、D(4番)が2着、F(6番)が3着
        Map<String, Integer> pay = new HashMap<>();
        pay.put("単勝:1", 350);
        pay.put("複勝:1", 150);
        pay.put("複勝:4", 400);
        pay.put("複勝:6", 900);
        pay.put("馬連:1-4", 2100);
        pay.put("ワイド:1-4", 700);
        pay.put("ワイド:1-6", 1800);
        pay.put("ワイド:4-6", 4200);
        pay.put("三連複:1-4-6", 15000);
        pay.put("三連単:1-4-6", 60000);
        List<BetLine> lines = betting.suggest(race(Map.of("A", 1, "D", 2, "F", 3)), pay);
        assertEquals(true, line(lines, "単勝").getHit());
        assertEquals(350, line(lines, "単勝").getReturnAmount());
        assertEquals(true, line(lines, "馬連").getHit());       // ◎1-△4
        assertEquals(2100, line(lines, "馬連").getReturnAmount());
        assertEquals(false, line(lines, "ワイド").getHit());    // ◎-○(2) ◎-▲(3) は外れ
        assertEquals(0, line(lines, "ワイド").getReturnAmount());
        assertEquals(false, line(lines, "三連複").getHit());    // 6番は印外
    }

    @Test
    void 払戻表の同着組も的中になる() {
        // 1着同着(A,B)・3着C → 三連単は 1-2-3 と 2-1-3 の両方が払戻表にある
        Map<String, Integer> pay = new HashMap<>();
        pay.put("三連単:1-2-3", 30000);
        pay.put("三連単:2-1-3", 28000);
        pay.put("単勝:1", 400);
        pay.put("単勝:2", 380);
        pay.put("複勝:1", 130);
        pay.put("複勝:2", 140);
        pay.put("複勝:3", 300);
        pay.put("ワイド:1-2", 500);
        pay.put("馬連:1-2", 900);
        pay.put("三連複:1-2-3", 4000);
        List<BetLine> lines = betting.suggest(race(Map.of("A", 1, "B", 1, "C", 3)), pay);
        assertEquals(true, line(lines, "三連単").getHit());
        assertEquals(30000, line(lines, "三連単").getReturnAmount());   // ◎→○→▲ のみ購入
        assertEquals(400, line(lines, "単勝").getReturnAmount());
    }

    @Test
    void 払戻キーは馬単と三連単だけ順序を保つ() {
        assertEquals("馬連:3-12", BettingService.payoutKey("馬連", 12, 3));
        assertEquals("三連複:2-5-9", BettingService.payoutKey("三連複", 9, 2, 5));
        assertEquals("三連単:9-2-5", BettingService.payoutKey("三連単", 9, 2, 5));
        assertEquals("馬単:12-3", BettingService.payoutKey("馬単", 12, 3));
    }

    @Test
    void 券種が欠けた払戻表は使わず着順で判定する() {
        // 三連単の行が欠けた部分取得。払戻表だけで判定すると三連単が「外れ」になってしまう
        Map<String, Integer> pay = new HashMap<>();
        pay.put("単勝:1", 350);
        pay.put("複勝:1", 150);
        pay.put("ワイド:1-2", 500);
        pay.put("馬連:1-2", 900);
        pay.put("三連複:1-2-3", 4000);
        List<BetLine> lines = betting.suggest(race(Map.of("A", 1, "B", 2, "C", 3)), pay);
        assertEquals(true, line(lines, "三連単").getHit());       // 着順で判定
        assertNull(line(lines, "三連単").getReturnAmount());      // 払戻額は不明
    }
}
