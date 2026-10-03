package com.faceprediction.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.junit.jupiter.api.Test;
import org.thymeleaf.context.Context;
import org.thymeleaf.spring5.SpringTemplateEngine;
import org.thymeleaf.templateresolver.ClassLoaderTemplateResolver;

/**
 * 展開想定図の座標変換と根拠の読み取りのテスト。
 * JSON は python/race_diagram.py が race_column.diagram に保存する形。
 */
class RaceDiagramServiceTest {

    private final RaceDiagramService service = new RaceDiagramService();

    private static final String JSON = "{\"direction\":\"左\",\"pace\":\"ハイペース\","
        + "\"evidence\":{\"pace\":{\"leaders\":[3,10],\"basis\":\"逃げ候補\",\"accuracy\":{\"ハイペース\":0.46},\"label\":\"ハイペース\"},"
        + "\"course\":\"東京芝1600は…\",\"model\":{\"races\":200,\"start_top4\":2.64,\"stretch_top4\":1.9},\"with_data\":2},"
        + "\"scenes\":[{\"key\":\"start\",\"title\":\"スタート〜最初のコーナー（想定）\",\"goal\":\"最初のコーナーへ\",\"side\":\"home\",\"horses\":["
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

    // ── テレビ（スタンド）から見た向き。描いた SVG は target/diagram-test/ に書き出す（column_audit の確認用）──
    //   スタンド前（home）: 内ラチ上、左回りは左→右・右回りは右→左 / 向正面（back）: 内ラチ下、左回りは右→左・右回りは左→右

    private static final String TURN_JSON = "{\"direction\":\"%s\",\"course\":\"%s\",%s\"scenes\":["
        + "{\"key\":\"start\",\"title\":\"図1\",\"goal\":\"最初のコーナーへ\",\"side\":\"%s\",\"horses\":["
        + "{\"num\":1,\"waku\":1,\"lane\":0,\"x\":0.0,\"mark\":\"◎\"},{\"num\":2,\"waku\":2,\"lane\":2,\"x\":1.0}]},"
        + "{\"key\":\"stretch\",\"title\":\"図2\",\"goal\":\"ゴール\",\"side\":\"home\",\"horses\":["
        + "{\"num\":1,\"waku\":1,\"lane\":0,\"x\":0.0,\"mark\":\"◎\"},{\"num\":2,\"waku\":2,\"lane\":2,\"x\":1.0}]}]}";

    @Test
    void 京都2400はスタートも直線もスタンド前_内ラチ上で右から左() throws Exception {
        List<Map<String, Object>> sc = service.scenes(String.format(TURN_JSON, "右", "京都芝2400", "\"io\":\"外\",", "home"));
        for (int i = 0; i < 2; i++) assertScene(sc.get(i), 44, true);
        String html = render(sc, "kyoto2400");
        assertTrue(html.contains("data-course=\"京都芝2400(外)\""));
        assertTrue(html.contains("◀ ゴール") && html.contains("◀ 最初のコーナーへ"));
        assertTrue(html.contains("x1=\"30\""), "ゴール板は左");
    }

    @Test
    void 東京1800のスタートは向正面_内ラチ下で右から左_直線は内ラチ上で左から右() throws Exception {
        List<Map<String, Object>> sc = service.scenes(String.format(TURN_JSON, "左", "東京芝1800", "", "back"));
        assertScene(sc.get(0), 216, true);
        assertScene(sc.get(1), 44, false);
        String html = render(sc, "tokyo1800");
        assertTrue(html.contains("◀ 最初のコーナーへ") && html.contains("ゴール ▶"));
        assertTrue(html.contains("x1=\"770\""), "ゴール板は右");
    }

    @Test
    void 右回りの向正面スタートは内ラチ下で左から右() throws Exception {
        List<Map<String, Object>> sc = service.scenes(String.format(TURN_JSON, "右", "京都芝1600", "\"io\":\"外\",", "back"));
        assertScene(sc.get(0), 216, false);
        assertScene(sc.get(1), 44, true);
        render(sc, "kyoto1600");
    }

    @Test
    void スタート地点の分からない古い図は図2だけ() {
        String old = String.format(TURN_JSON, "左", "東京芝1800", "", "x").replace(",\"side\":\"x\"", "");
        List<Map<String, Object>> sc = service.scenes(old);
        assertEquals(1, sc.size());
        assertEquals("stretch", sc.get(0).get("key"));
    }

    /** railY（44=上 / 216=下）と、先頭（馬番1・レーン0）の位置: 進む向きの前にいて、内ラチ側にいる */
    private static void assertScene(Map<String, Object> scene, int railY, boolean toLeft) {
        assertEquals(railY, scene.get("railY"));
        assertEquals(toLeft, scene.get("toLeft"));
        Map<String, Object> lead = horse(scene, 1), last = horse(scene, 2);
        long lx = (long) lead.get("cx"), bx = (long) last.get("cx"), ly = (long) lead.get("cy"), by = (long) last.get("cy");
        assertTrue(toLeft ? lx < bx : lx > bx, "先頭が進む向きの前");
        assertTrue(railY < 100 ? ly < by : ly > by, "レーン0が内ラチ側");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> horse(Map<String, Object> scene, int num) {
        return ((List<Map<String, Object>>) scene.get("horses")).stream()
            .filter(h -> (int) h.get("num") == num).findFirst().orElseThrow();
    }

    private static String render(List<Map<String, Object>> scenes, String name) throws Exception {
        ClassLoaderTemplateResolver resolver = new ClassLoaderTemplateResolver();
        resolver.setPrefix("templates/");
        resolver.setSuffix(".html");
        SpringTemplateEngine engine = new SpringTemplateEngine();
        engine.setTemplateResolver(resolver);
        StringBuilder html = new StringBuilder();
        for (int i = 0; i < scenes.size(); i++) {
            Context ctx = new Context();
            ctx.setVariable("sc", scenes.get(i));
            ctx.setVariable("idx", i);
            html.append(engine.process("fragments/diagram", Set.of("svg"), ctx));
        }
        Path out = Path.of("target", "diagram-test", name + ".html");
        Files.createDirectories(out.getParent());
        Files.writeString(out, "<div class=\"diagram\">" + html + "</div>");
        return html.toString();
    }
}
