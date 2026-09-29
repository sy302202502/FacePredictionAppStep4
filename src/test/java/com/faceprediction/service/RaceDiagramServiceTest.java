package com.faceprediction.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

/**
 * 展開想定図の座標変換と根拠の読み取りのテスト。
 * JSON は python/race_diagram.py が race_column.diagram に保存する形。
 */
class RaceDiagramServiceTest {

    private final RaceDiagramService service = new RaceDiagramService();

    private static final String JSON = "{\"direction\":\"左\",\"pace\":\"ハイペース\","
        + "\"evidence\":{\"pace\":{\"leaders\":[3,10],\"basis\":\"逃げ候補\",\"accuracy\":{\"ハイペース\":0.46},\"label\":\"ハイペース\"},"
        + "\"course\":\"東京芝1600は…\",\"model\":{\"races\":200,\"start_top4\":2.64,\"stretch_top4\":1.9},\"with_data\":2},"
        + "\"scenes\":[{\"key\":\"start\",\"title\":\"スタート〜最初のコーナー（想定）\",\"goal\":\"最初のコーナーへ\",\"horses\":["
        + "{\"num\":10,\"waku\":7,\"mark\":\"◎\",\"name\":\"A\",\"x\":0,\"lane\":0,\"why\":\"近6走の序盤 平均1.2番手相当\"},"
        + "{\"num\":3,\"waku\":null,\"mark\":null,\"name\":\"B\",\"x\":1,\"lane\":2}]},"
        + "{\"key\":\"stretch\",\"title\":\"最後の直線（想定）\",\"goal\":\"ゴール\",\"horses\":[]}]}";

    @Test
    void 左回りは内ラチが上_先頭は右端() {
        List<Map<String, Object>> scenes = service.scenes(JSON);
        assertEquals(2, scenes.size());
        Map<String, Object> s = scenes.get(0);
        assertEquals(44, s.get("railY"));                       // 左回り: 内ラチは上側
        Map<String, Object> top = ((List<Map<String, Object>>) s.get("horses")).get(0);
        assertEquals(730L, top.get("cx"));                      // x=0（先頭）は右端
        assertEquals(62L, top.get("cy"));                       // レーン0 = 内ラチ沿い
        assertEquals("#f57c00", top.get("fill"));               // 7枠 = 橙
        assertEquals("#f5d878", top.get("stroke"));             // ◎ は金の縁
        assertEquals("近6走の序盤 平均1.2番手相当", top.get("why"));
        Map<String, Object> other = ((List<Map<String, Object>>) s.get("horses")).get(1);
        assertEquals("#9e9e9e", other.get("fill"));             // 枠番なしは灰色
        assertNull(other.get("why"));
        assertEquals(true, scenes.get(1).get("finish"));
    }

    @Test
    void 根拠の読み取り() {
        Map<String, Object> ev = service.evidence(JSON);
        assertEquals("ハイペース", ev.get("pace"));
        assertEquals("3・10番（2頭）", ev.get("leaders"));
        assertEquals(46L, ev.get("paceAccuracy"));
        assertEquals("2.6", ev.get("startTop4"));
        assertEquals(200, ev.get("modelRaces"));
        assertEquals(2, ev.get("total"));
    }

    @Test
    void 壊れたJSONや空はnull() {
        assertNull(service.scenes(null));
        assertNull(service.scenes("{broken"));
        assertNull(service.evidence(""));
        assertNull(service.evidence("{\"scenes\":[]}"));        // 根拠の無い古い図
    }
}
