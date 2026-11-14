package com.faceprediction.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import com.faceprediction.entity.RaceSpecificResult;

/** 写真が無い海外馬（顔面分析なし）の扱い: レース内の顔の平均で補い、統計で順位に入れる */
class FaceRankingServiceTest {

    private final FaceRankingService ranking = new FaceRankingService();

    private Map<String, Object> row(String name, String id, Double face, Double stats, int num) {
        Map<String, Object> m = new HashMap<>();
        m.put("horse_name", name); m.put("horse_id", id); m.put("face_score", face);
        m.put("score", stats); m.put("horse_number", num);
        return m;
    }

    @Test
    void 顔面の点が無い馬も統計で順位に入る() {
        List<RaceSpecificResult> r = ranking.rank(List.of(
            row("A", "000a000001", 80.0, 50.0, 1),
            row("B", "000a000002", null, 70.0, 2),   // 写真なしの海外馬
            row("C", "2021100001", 85.0, 55.0, 3),
            row("D", "2021100002", null, 90.0, 4)));  // 日本馬で顔面の点が無い・統計は最上位
        // 2026-11-14: 日本馬も末尾に回さない（統計2位の馬が無印のまま勝つことがあった）
        assertEquals("D", r.get(0).getHorseName());
        assertNotNull(r.get(0).getScore());
        assertEquals("写真がないため鬼眼の対象外（統計で評価）", r.get(0).getComment());
        assertEquals("B", r.get(1).getHorseName());
        assertEquals("写真がないため鬼眼の対象外（統計で評価）", r.get(1).getComment());
    }

    @Test
    void 写真はあるが分析がまだの馬は分析待ちと表示する() {
        Map<String, Object> d = row("D", "2021100002", null, 90.0, 2);
        d.put("image_path", "/uploads/candidates/2021100002.jpg");
        List<RaceSpecificResult> r = ranking.rank(List.of(row("A", "2021100001", 80.0, 50.0, 1), d));
        assertEquals("D", r.get(0).getHorseName());
        assertEquals("鬼眼の分析がまだのため統計で評価", r.get(0).getComment());
    }

    @Test
    void 全頭が未分析ならスコア無しのまま() {
        List<RaceSpecificResult> r = ranking.rank(List.of(
            row("A", "2021100001", null, 50.0, 1), row("B", "2021100002", null, 70.0, 2)));
        assertNull(r.get(0).getScore());
        assertNull(r.get(1).getScore());
    }
}
