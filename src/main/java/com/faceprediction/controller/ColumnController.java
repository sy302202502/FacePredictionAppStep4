package com.faceprediction.controller;

import java.sql.Date;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

/**
 * コラムのページ。毎週の重賞について、木曜・金曜に出す「週中コラム」（python/week_column.py が作成。
 * 事実だけで組み立て、顔面分析・鬼眼の印は使わない）を週ごとにまとめて表示する。
 * 土日の「鬼眼コラム」（予想画面）があるレースは、そこへの導線も出す。
 *   /column            … いちばん新しい週
 *   /column?week=…     … その週（月曜の日付 yyyy-MM-dd）
 */
@Controller
@RequestMapping("/column")
public class ColumnController {

    private static final String[] WEEKDAYS = {"月", "火", "水", "木", "金", "土", "日"};
    private static final DateTimeFormatter MD = DateTimeFormatter.ofPattern("M月d日");

    @Autowired private JdbcTemplate jdbc;

    @GetMapping
    public String show(@RequestParam(required = false) String week, Model model) {
        List<LocalDate> weeks;
        try {
            weeks = jdbc.queryForList(
                "SELECT DISTINCT date_trunc('week', race_date)::date AS wk FROM week_column " +
                "WHERE race_date IS NOT NULL ORDER BY wk DESC LIMIT 26", Date.class)
                .stream().map(Date::toLocalDate).collect(Collectors.toList());
        } catch (Exception e) {
            weeks = List.of();   // week_column 未作成（まだ一度もコラムを書いていない環境）
        }
        LocalDate selected = weeks.isEmpty() ? null : weeks.get(0);
        if (week != null) {
            try {
                LocalDate w = LocalDate.parse(week);
                if (weeks.contains(w)) selected = w;
            } catch (Exception ignore) { }
        }
        model.addAttribute("weeks", weeks.stream().map(w -> Map.of(
            "key", w.toString(),
            "label", w.plusDays(5).format(MD) + "・" + w.plusDays(6).format(MD) + "の週"))
            .collect(Collectors.toList()));
        model.addAttribute("selectedWeek", selected == null ? null : selected.toString());
        model.addAttribute("weekLabel", selected == null ? null
            : selected.plusDays(5).format(MD) + "・" + selected.plusDays(6).format(MD));
        model.addAttribute("races", selected == null ? List.of() : racesOf(selected));
        return "column/index";
    }

    /** その週のレースごとに、金曜版（無ければ木曜版）を本文として、もう一方を「前の版」として返す */
    private List<Map<String, Object>> racesOf(LocalDate monday) {
        List<Map<String, Object>> rows = jdbc.queryForList(
            "SELECT wc.race_id, wc.edition, wc.race_name, wc.race_date, wc.grade, wc.title, wc.body, " +
            "       wc.generator, wc.updated_at, " +
            "       EXISTS (SELECT 1 FROM race_column rc WHERE rc.race_id = wc.race_id) AS has_oni " +
            "FROM week_column wc WHERE wc.race_date >= ? AND wc.race_date < ? " +
            // 同じレースは 金曜版 → 木曜版 の順（新しい版を本文に。文字列順の DESC だと thu が先に来てしまう）
            "ORDER BY wc.race_date, wc.grade, wc.race_id, CASE wc.edition WHEN 'fri' THEN 0 ELSE 1 END",
            Date.valueOf(monday), Date.valueOf(monday.plusDays(7)));
        Map<String, Map<String, Object>> byRace = new LinkedHashMap<>();
        for (Map<String, Object> r : rows) {
            Map<String, Object> race = byRace.computeIfAbsent((String) r.get("race_id"), k -> {
                Map<String, Object> m = new LinkedHashMap<>();
                LocalDate d = ((Date) r.get("race_date")).toLocalDate();
                m.put("raceId", k);
                m.put("raceName", r.get("race_name"));
                m.put("grade", r.get("grade"));
                m.put("dateLabel", d.format(MD) + "（" + WEEKDAYS[d.getDayOfWeek().getValue() - 1] + "）");
                m.put("hasOni", r.get("has_oni"));
                m.put("editions", new ArrayList<Map<String, Object>>());
                return m;
            });
            Map<String, Object> ed = new LinkedHashMap<>();
            ed.put("label", "fri".equals(r.get("edition")) ? "金曜版" : "木曜版");
            ed.put("title", r.get("title"));
            ed.put("paragraphs", Arrays.stream(((String) r.get("body")).split("\\n\\s*\\n"))
                .map(String::trim).filter(p -> !p.isEmpty()).collect(Collectors.toList()));
            ed.put("generator", r.get("generator"));
            ed.put("updated", r.get("updated_at"));
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> eds = (List<Map<String, Object>>) race.get("editions");
            eds.add(ed);   // 金曜版 → 木曜版 の順
        }
        return new ArrayList<>(byRace.values());
    }
}
