package com.faceprediction.controller;

import java.net.CookieManager;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import com.faceprediction.entity.RaceSpecificResult;
import com.faceprediction.service.FaceRankingService;
import com.faceprediction.service.RaceSelectionService;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * 東スポ競馬の指数・記者印の参考パネル（管理者のみ）。
 *
 * 利用規約はコンテンツの転載・二次利用・商業利用を禁じているため、
 *   ・ログインした本人（管理者）だけが見られる画面にする（公開ページには出さない）
 *   ・DB には保存しない（開いたときに東スポから取得し、10分だけメモリに置く）
 * .env の TOSPO_ENABLED=1 のときだけ動く。
 */
@Controller
@RequestMapping("/tospo")
public class TospoController {

    private static final Logger log = LoggerFactory.getLogger(TospoController.class);
    private static final String BASE = "https://tospo-keiba.jp";
    private static final long CACHE_MS = 10 * 60 * 1000L;
    private static final Pattern TOKEN = Pattern.compile("name=\"_token\"\\s+value=\"([^\"]+)\"");
    /** 記者印の種類 → 表示。2=◎ 3=○ 4=▲、5・6 は△系 */
    private static final Map<Integer, String> MARKS = Map.of(2, "◎", 3, "○", 4, "▲", 5, "△", 6, "△");

    @Value("${TOSPO_ENABLED:0}")      private String enabled;
    @Value("${TOSPO_LOGIN_EMAIL:}")   private String email;
    @Value("${TOSPO_PASSWORD:}")      private String password;

    @Autowired private RaceSelectionService selectionService;
    @Autowired private FaceRankingService   rankingService;
    @Autowired private org.springframework.jdbc.core.JdbcTemplate jdbc;

    private final ObjectMapper mapper = new ObjectMapper();
    private final HttpClient http = HttpClient.newBuilder()
        .cookieHandler(new CookieManager())
        .connectTimeout(Duration.ofSeconds(10))
        .followRedirects(HttpClient.Redirect.NORMAL)
        .build();
    private final Map<String, Object[]> cache = new ConcurrentHashMap<>();  // raceId → {取得時刻, rows}

    @GetMapping
    public String show(@RequestParam(required = false) String raceId, Model model) {
        model.addAttribute("enabled", "1".equals(enabled.trim()));
        List<Map<String, Object>> races = selectionService.listRaces();
        model.addAttribute("raceOptions", races);
        String selectedId = selectionService.resolve(raceId, null, races);
        model.addAttribute("selectedRaceId", selectedId);
        model.addAttribute("selectedRace", selectionService.nameOf(selectedId, races));
        if (!"1".equals(enabled.trim()) || selectedId == null) {
            model.addAttribute("rows", List.of());
            return "tospo/index";
        }
        try {
            Object[] data = rowsFor(selectedId);
            model.addAttribute("rows", data[1]);
            model.addAttribute("loggedIn", data[2]);
        } catch (Exception e) {
            log.warn("東スポの取得に失敗: {}", e.getMessage());
            model.addAttribute("error", "東スポ競馬からの取得に失敗しました（" + e.getClass().getSimpleName() + "）");
            model.addAttribute("rows", List.of());
        }
        return "tospo/index";
    }

    /**
     * {取得時刻, 行, ログイン状態}。Cookie を共有するので、取得〜ログイン〜再取得を1つずつ直列に行う
     * （管理者1人の参考画面なので直列化による待ちは問題にならない）
     */
    private synchronized Object[] rowsFor(String raceId) throws Exception {
        Object[] hit = cache.get(raceId);
        if (hit != null && System.currentTimeMillis() - (long) hit[0] < CACHE_MS) {
            return hit;
        }
        JsonNode rating = get(raceId, "rating");
        if (!rating.path("isLogin").asBoolean() && !email.isBlank() && login()) {
            rating = get(raceId, "rating");
        }
        boolean loggedIn = rating.path("isLogin").asBoolean();
        JsonNode card = get(raceId, "card");

        // 鬼眼の印（予想画面と同じ順位）: 馬ID → 印
        Map<String, String> oniMarks = new HashMap<>();
        List<RaceSpecificResult> ranked = rankingService.rank(jdbc.queryForList(
            "SELECT sp.horse_id, sp.horse_name, sp.face_score, sp.score, re.horse_number, re.post_position " +
            "FROM stats_prediction sp JOIN race_entry re ON re.race_id = sp.race_id AND re.horse_id = sp.horse_id " +
            "WHERE sp.race_id = ?", raceId));
        for (RaceSpecificResult r : ranked) {
            if (r.getScore() != null && r.getRankPosition() <= 5) {
                oniMarks.put(r.getHorseId(), FaceRankingService.markOf(r.getRankPosition()));
            }
        }

        // 記者印の集計: raceEntryId → {◎,○,▲,△}
        Map<Long, int[]> markCount = new HashMap<>();
        for (JsonNode perReporter : card.path("raceForecast").path("reporterMarks")) {
            for (JsonNode m : perReporter) {
                String mark = MARKS.get(m.path("reporterMarkType").asInt());
                if (mark == null) continue;
                int[] c = markCount.computeIfAbsent(m.path("raceEntryId").asLong(), k -> new int[4]);
                c["◎○▲△".indexOf(mark)]++;
            }
        }

        Map<Long, String> idByEntry = new HashMap<>();
        for (JsonNode e : rating.path("raceEntryList")) {
            idByEntry.put(e.path("raceEntryId").asLong(), e.path("studbookCode").asText(null));
        }
        List<Map<String, Object>> rows = new ArrayList<>();
        for (JsonNode h : rating.path("raceRatingList")) {
            long entryId = h.path("raceEntryId").asLong();
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("num", h.path("horseNumber").isNull() ? null : h.path("horseNumber").asInt());
            row.put("name", h.path("horseName").asText());
            row.put("withdrawn", h.path("withdrawn").asInt() != 0);
            row.put("oni", oniMarks.get(idByEntry.get(entryId)));
            row.put("yearly", rating(h, "yearlyBestRating"));
            row.put("length", rating(h, "bestLengthRating"));
            row.put("course", rating(h, "bestCourseRating"));
            row.put("best", rating(h, "bestRating"));
            int[] c = markCount.getOrDefault(entryId, new int[4]);
            row.put("marks", c);
            row.put("markScore", c[0] * 5 + c[1] * 3 + c[2] * 2 + c[3]);
            rows.add(row);
        }
        rows.sort((a, b) -> Integer.compare((int) b.get("markScore"), (int) a.get("markScore")));
        Object[] result = {System.currentTimeMillis(), rows, loggedIn};
        cache.put(raceId, result);
        return result;
    }

    private static Integer rating(JsonNode h, String key) {
        JsonNode v = h.path(key).path("rating");
        return v.isNumber() ? v.asInt() : null;
    }

    private JsonNode get(String raceId, String page) throws Exception {
        HttpRequest req = HttpRequest.newBuilder(URI.create(BASE + "/race/detail/" + raceId + "/" + page))
            .header("X-Requested-With", "XMLHttpRequest").header("Accept", "application/json")
            .header("User-Agent", "Mozilla/5.0").timeout(Duration.ofSeconds(15)).GET().build();
        HttpResponse<String> res = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (res.statusCode() != 200) throw new IllegalStateException("HTTP " + res.statusCode());
        return mapper.readTree(res.body()).path("body");
    }

    /** 会員ログイン。成功したかは次の API の isLogin で判定する */
    private boolean login() {
        try {
            HttpResponse<String> page = http.send(HttpRequest.newBuilder(URI.create(BASE + "/login"))
                .header("User-Agent", "Mozilla/5.0").GET().build(), HttpResponse.BodyHandlers.ofString());
            Matcher m = TOKEN.matcher(page.body());
            if (!m.find()) return false;
            String form = "_token=" + enc(m.group(1)) + "&email=" + enc(email) + "&password=" + enc(password)
                + "&callBackUrl=";
            http.send(HttpRequest.newBuilder(URI.create(BASE + "/login"))
                .header("Content-Type", "application/x-www-form-urlencoded").header("User-Agent", "Mozilla/5.0")
                .POST(HttpRequest.BodyPublishers.ofString(form)).build(), HttpResponse.BodyHandlers.ofString());
            return true;
        } catch (Exception e) {
            log.warn("東スポのログインに失敗: {}", e.getClass().getSimpleName());
            return false;
        }
    }

    private static String enc(String s) {
        return URLEncoder.encode(s, StandardCharsets.UTF_8);
    }
}
