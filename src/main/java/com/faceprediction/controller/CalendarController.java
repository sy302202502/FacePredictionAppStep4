package com.faceprediction.controller;

import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
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


@Controller
@RequestMapping("/calendar")
public class CalendarController {

    @Autowired private JdbcTemplate        jdbc;

    @GetMapping
    public String show(Model model) {
        LocalDate today = LocalDate.now();
        LocalDate limit = today.plusDays(21);

        // 表示期間（過去3日〜未来21日）の開催を race_id 単位で1クエリ取得。
        // 旧実装は race_name 単位で、前年の同名重賞の頭数が合算され（18頭＋16頭＝34頭など）、
        // 分析済み判定も名前の部分一致だったため前年の分析で「分析済み」になっていた
        List<Object[]> upcoming = jdbc.query(
            "SELECT MIN(re.race_name), MIN(re.race_date), MIN(re.race_category), MIN(re.distance), " +
            "       MIN(re.surface), MIN(re.venue), re.race_id, COUNT(*), " +
            "       EXISTS (SELECT 1 FROM stats_prediction sp " +
            "               WHERE sp.race_id = re.race_id AND sp.face_comment IS NOT NULL) " +
            "FROM race_entry re " +
            "WHERE re.race_date BETWEEN ? AND ? " +
            "GROUP BY re.race_id",
            (rs, i) -> new Object[] {
                rs.getString(1), rs.getDate(2), rs.getString(3), rs.getObject(4),
                rs.getString(5), rs.getString(6), rs.getString(7), rs.getLong(8), rs.getBoolean(9)
            },
            java.sql.Date.valueOf(today.minusDays(3)), java.sql.Date.valueOf(limit));

        List<Map<String, Object>> events = new ArrayList<>();
        for (Object[] row : upcoming) {
            // [race_name, race_date, race_category, distance, surface, venue, race_id, 頭数, 分析済み]
            String    raceName    = row[0] != null ? row[0].toString() : "";
            LocalDate raceDate    = null;
            if (row[1] != null) {
                if (row[1] instanceof java.sql.Date) {
                    raceDate = ((java.sql.Date) row[1]).toLocalDate();
                } else {
                    try { raceDate = LocalDate.parse(row[1].toString()); } catch (Exception ignored) {}
                }
            }
            String    category    = row[2] != null ? row[2].toString() : "";
            Object    distObj     = row[3];
            String    surface     = row[4] != null ? row[4].toString() : "";
            String    venue       = row[5] != null ? row[5].toString() : "";

            if (raceDate == null) continue;
            // 過去 3日〜未来 21日 のみ表示
            if (raceDate.isBefore(today.minusDays(3))) continue;
            if (raceDate.isAfter(limit)) continue;

            long daysLeft = ChronoUnit.DAYS.between(today, raceDate);
            boolean isAnalyzed = (Boolean) row[8];
            boolean isPast = raceDate.isBefore(today);

            long entryCount = (Long) row[7];

            String urgency;
            if (isPast) {
                urgency = "past";
            } else if (daysLeft == 0) {
                urgency = "today";
            } else if (daysLeft <= 2) {
                urgency = "urgent";
            } else if (daysLeft <= 7) {
                urgency = "soon";
            } else {
                urgency = "future";
            }

            String categoryLabel;
            switch (category) {
                case "sprint": categoryLabel = "短距離"; break;
                case "mile":   categoryLabel = "マイル"; break;
                case "middle": categoryLabel = "中距離"; break;
                case "long":   categoryLabel = "長距離"; break;
                case "dirt":   categoryLabel = "ダート"; break;
                case "jump":   categoryLabel = "障害"; break;
                default:       categoryLabel = category; break;
            }

            Map<String, Object> ev = new LinkedHashMap<>();
            ev.put("raceName",      raceName);
            ev.put("raceDate",      raceDate.toString());
            ev.put("daysLeft",      daysLeft);
            ev.put("isAnalyzed",    isAnalyzed);
            ev.put("isPast",        isPast);
            ev.put("urgency",       urgency);
            ev.put("categoryLabel", categoryLabel);
            ev.put("surface",       surface);
            ev.put("distance",      distObj != null ? distObj.toString() : "-");
            ev.put("venue",         venue);
            ev.put("entryCount",    entryCount);
            events.add(ev);
        }

        // 日付でソート
        events.sort((a, b) -> a.get("raceDate").toString().compareTo(b.get("raceDate").toString()));

        // 日付ごとにグループ化
        Map<String, List<Map<String, Object>>> grouped = events.stream()
            .collect(Collectors.groupingBy(
                e -> e.get("raceDate").toString(),
                LinkedHashMap::new,
                Collectors.toList()
            ));

        model.addAttribute("groupedEvents", grouped);
        model.addAttribute("today",         today.toString());
        model.addAttribute("analyzedCount", events.stream().filter(e -> Boolean.TRUE.equals(e.get("isAnalyzed"))).count());
        model.addAttribute("totalEvents",   events.size());

        return "calendar/index";
    }
}
