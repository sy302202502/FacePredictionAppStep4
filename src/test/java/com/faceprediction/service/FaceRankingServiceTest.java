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
    void 写真の無い海外馬は統計で順位に入り日本馬の未分析は末尾() {
        List<RaceSpecificResult> r = ranking.rank(List.of(
            row("A", "000a000001", 80.0, 50.0, 1),
            row("B", "000a000002", null, 70.0, 2),   // 写真なしの海外馬・統計は最上位
            row("C", "2021100001", 85.0, 55.0, 3),
            row("D", "2021100002", null, 90.0, 4)));  // 日本馬の未分析は従来どおり末尾
        assertEquals("B", r.get(0).getHorseName());
        assertNotNull(r.get(0).getScore());
        assertEquals("写真がないため鬼眼の対象外（統計で評価）", r.get(0).getComment());
        assertEquals("D", r.get(3).getHorseName());
        assertNull(r.get(3).getScore());
    }
}
