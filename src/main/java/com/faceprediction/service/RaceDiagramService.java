package com.faceprediction.service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * 鬼眼コラムの「展開の想定図」を SVG で描くための座標を作る。
 * 位置（前後 x と内外 lane）は python/race_diagram.py がコラム作成時に計算して race_column.diagram に保存済み。
 * ここでは画面の座標・枠の色・印の強調に変換するだけ（描画はテンプレートの SVG）。
 */
@Service
public class RaceDiagramService {

    /** SVG の大きさ（viewBox）と、コース帯の上下端 */
    public static final int WIDTH = 800;
    public static final int HEIGHT = 250;
    private static final int TRACK_TOP = 40;
    private static final int TRACK_BOTTOM = 220;
    private static final int FRONT_X = 730;   // 先頭の位置（右が進行方向）
    private static final int SPAN_X = 640;    // 先頭〜最後方の幅
    private static final int RAIL_GAP = 22;   // 内ラチからの最初のレーンまで
    private static final int LANE_GAP = 34;   // レーン間隔

    /** JRA の枠の色（1白 2黒 3赤 4青 5黄 6緑 7橙 8桃）と、その上の数字の色 */
    private static final String[] WAKU_FILL = {"#9e9e9e", "#ffffff", "#222222", "#e53935", "#1e5bd8",
                                               "#fdd835", "#2e9e44", "#f57c00", "#f48fb1"};
    private static final String[] WAKU_TEXT = {"#000000", "#111111", "#ffffff", "#ffffff", "#ffffff",
                                               "#111111", "#ffffff", "#ffffff", "#111111"};

    private final ObjectMapper mapper = new ObjectMapper();

    /**
     * 図の根拠（想定ペースの根拠・コースの傾向・この図の作り方の検証成績）。無ければ null。
     * キー: pace, leaders（逃げ候補の馬番「3・10番」）, paceAccuracy（その判定の的中率 %）, course,
     *       modelRaces, modelKind（試算/検証）, startTop4, stretchTop4（平均 x/4）, baseStretchTop4（従来の方法）,
     *       paceTotal（想定ペースの的中率 %）, withData, total
     */
    public Map<String, Object> evidence(String diagramJson) {
        if (diagramJson == null || diagramJson.isBlank()) return null;
        try {
            JsonNode root = mapper.readTree(diagramJson);
            JsonNode ev = root.path("evidence");
            if (ev.isMissingNode()) return null;
            Map<String, Object> m = new LinkedHashMap<>();
            String pace = ev.path("pace").path("label").asText(root.path("pace").asText(""));
            m.put("pace", pace);
            List<String> leaders = new ArrayList<>();
            ev.path("pace").path("leaders").forEach(n -> leaders.add(n.asText()));
            m.put("leaders", leaders.isEmpty() ? "いない（0頭）" : String.join("・", leaders) + "番（" + leaders.size() + "頭）");
            m.put("basis", ev.path("pace").path("basis").asText("逃げ候補"));
            JsonNode acc = ev.path("pace").path("accuracy").path(pace);
            m.put("paceAccuracy", acc.isNumber() ? Math.round(acc.asDouble() * 100) : null);
            m.put("course", ev.path("course").isTextual() ? ev.path("course").asText() : null);
            JsonNode model = ev.path("model");
            m.put("modelRaces", model.path("races").isNumber() ? model.path("races").asInt() : null);
            m.put("startTop4", model.path("start_top4").isNumber() ? String.format("%.1f", model.path("start_top4").asDouble()) : null);
            m.put("stretchTop4", model.path("stretch_top4").isNumber() ? String.format("%.1f", model.path("stretch_top4").asDouble()) : null);
            m.put("modelKind", model.path("kind").asText("検証"));
            m.put("baseStretchTop4", model.path("base_stretch_top4").isNumber() ? String.format("%.1f", model.path("base_stretch_top4").asDouble()) : null);
            m.put("paceTotal", model.path("pace_total").isNumber() ? Math.round(model.path("pace_total").asDouble() * 100) : null);
            m.put("withData", ev.path("with_data").asInt());
            int total = 0;
            for (JsonNode s : root.path("scenes")) { total = s.path("horses").size(); break; }
            m.put("total", total);
            return m;
        } catch (Exception e) {
            return null;
        }
    }

    /** diagram の JSON → 画面用の場面リスト。壊れていれば null */
    public List<Map<String, Object>> scenes(String diagramJson) {
        if (diagramJson == null || diagramJson.isBlank()) return null;
        try {
            JsonNode root = mapper.readTree(diagramJson);
            String direction = root.path("direction").asText("右");
            // 右回りは進行方向の右手（画面の下側）が内ラチ、左回りは上側。直線コースは下側を外ラチとして描く
            boolean railBottom = !"左".equals(direction);
            List<Map<String, Object>> scenes = new ArrayList<>();
            for (JsonNode s : root.path("scenes")) {
                List<Map<String, Object>> horses = new ArrayList<>();
                for (JsonNode h : s.path("horses")) {
                    int lane = h.path("lane").asInt();
                    int waku = h.path("waku").isInt() ? h.path("waku").asInt() : 0;
                    if (waku < 0 || waku > 8) waku = 0;
                    double x = FRONT_X - h.path("x").asDouble() * SPAN_X;
                    double y = railBottom ? TRACK_BOTTOM - RAIL_GAP - lane * LANE_GAP
                                          : TRACK_TOP + RAIL_GAP + lane * LANE_GAP;
                    String mark = h.path("mark").isTextual() ? h.path("mark").asText() : null;
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("num", h.path("num").asInt());
                    m.put("name", h.path("name").asText(""));
                    m.put("why", h.path("why").isTextual() ? h.path("why").asText() : null);
                    m.put("cx", Math.round(x));
                    m.put("cy", Math.round(y));
                    m.put("fill", WAKU_FILL[waku]);
                    m.put("textFill", WAKU_TEXT[waku]);
                    m.put("mark", mark);
                    // ◎は金、○▲は橙で縁取り、それ以外は細い縁
                    m.put("stroke", "◎".equals(mark) ? "#f5d878" : ("○".equals(mark) || "▲".equals(mark)) ? "#ff8000" : "#0b0e0b");
                    m.put("strokeWidth", mark != null && ("◎○▲".contains(mark)) ? 4 : 1.5);
                    horses.add(m);
                }
                Map<String, Object> scene = new LinkedHashMap<>();
                scene.put("key", s.path("key").asText());
                scene.put("direction", direction);   // 監査用（column_audit が回りと内ラチの位置を照合する）
                scene.put("title", s.path("title").asText());
                scene.put("goal", s.path("goal").asText());
                scene.put("horses", horses);
                scene.put("railY", railBottom ? TRACK_BOTTOM - 4 : TRACK_TOP + 4);
                scene.put("outerY", railBottom ? TRACK_TOP + 4 : TRACK_BOTTOM - 4);
                scene.put("finish", "stretch".equals(s.path("key").asText()));
                scenes.add(scene);
            }
            return scenes.isEmpty() ? null : scenes;
        } catch (Exception e) {
            return null;
        }
    }
}
