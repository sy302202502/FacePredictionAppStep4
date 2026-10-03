package com.faceprediction.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Set;

import org.junit.jupiter.api.Test;
import org.thymeleaf.spring5.SpringTemplateEngine;
import org.thymeleaf.context.Context;
import org.thymeleaf.templateresolver.ClassLoaderTemplateResolver;

/**
 * 展開図はテレビで見る向きで描く: 内ラチはいつも上、左回りは左→右、右回りは右→左（ゴールが左）。
 * 描いた SVG は target/diagram-test/ に書き出す（python/column_audit.py の照合の確認にも使う）。
 */
class RaceDiagramServiceTest {

    private static final String JSON = "{\"direction\":\"%s\",\"scenes\":["
        + "{\"key\":\"start\",\"title\":\"図1\",\"goal\":\"最初のコーナーへ\",\"horses\":["
        + "{\"num\":1,\"waku\":1,\"lane\":0,\"x\":0.0,\"mark\":\"◎\"},{\"num\":2,\"waku\":2,\"lane\":2,\"x\":1.0}]},"
        + "{\"key\":\"stretch\",\"title\":\"図2\",\"goal\":\"ゴール\",\"horses\":["
        + "{\"num\":1,\"waku\":1,\"lane\":0,\"x\":0.0,\"mark\":\"◎\"},{\"num\":2,\"waku\":2,\"lane\":2,\"x\":1.0}]}]}";

    private final RaceDiagramService service = new RaceDiagramService();

    @Test
    void 右回りは内ラチが上で右から左へ走る() throws Exception {
        List<Map<String, Object>> scenes = service.scenes(String.format(JSON, "右"));
        Map<String, Object> lead = horse(scenes.get(1), 1), last = horse(scenes.get(1), 2);
        assertEquals(44, scenes.get(1).get("railY"));
        assertTrue((long) lead.get("cx") < (long) last.get("cx"), "先頭が左（ゴール側）");
        assertTrue((long) lead.get("cy") < (long) last.get("cy"), "内（レーン0）が上");
        String svg = render(scenes.get(1), "right");
        assertTrue(svg.contains("data-travel=\"left\""));
        assertTrue(svg.contains("◀ ゴール"));
        assertTrue(svg.contains("x1=\"30\""), "ゴール板は左");
    }

    @Test
    void 左回りは内ラチが上で左から右へ走る() throws Exception {
        List<Map<String, Object>> scenes = service.scenes(String.format(JSON, "左"));
        Map<String, Object> lead = horse(scenes.get(1), 1), last = horse(scenes.get(1), 2);
        assertEquals(44, scenes.get(1).get("railY"));
        assertTrue((long) lead.get("cx") > (long) last.get("cx"), "先頭が右（ゴール側）");
        assertTrue((long) lead.get("cy") < (long) last.get("cy"), "内（レーン0）が上");
        String svg = render(scenes.get(1), "left");
        assertTrue(svg.contains("data-travel=\"right\""));
        assertTrue(svg.contains("ゴール ▶"));
        assertTrue(svg.contains("x1=\"770\""), "ゴール板は右");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> horse(Map<String, Object> scene, int num) {
        return ((List<Map<String, Object>>) scene.get("horses")).stream()
            .filter(h -> (int) h.get("num") == num).findFirst().orElseThrow();
    }

    private static String render(Map<String, Object> scene, String name) throws Exception {
        ClassLoaderTemplateResolver resolver = new ClassLoaderTemplateResolver();
        resolver.setPrefix("templates/");
        resolver.setSuffix(".html");
        SpringTemplateEngine engine = new SpringTemplateEngine();
        engine.setTemplateResolver(resolver);
        Context ctx = new Context();
        ctx.setVariable("sc", scene);
        ctx.setVariable("idx", 1);
        String html = engine.process("fragments/diagram", Set.of("svg"), ctx);
        Path out = Path.of("target", "diagram-test", name + "_handed.html");
        Files.createDirectories(out.getParent());
        Files.writeString(out, html);
        return html;
    }
}
