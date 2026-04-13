package com.faceprediction.controller;

import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;

import com.faceprediction.repository.RaceEntryRepository;
import com.faceprediction.repository.RaceSpecificPredictionRepository;
import com.faceprediction.repository.RaceSpecificResultRepository;

@Controller
@RequestMapping("/calendar")
public class CalendarController {

    @Autowired private RaceEntryRepository               entryRepo;
    @Autowired private RaceSpecificPredictionRepository  patternRepo;
    @Autowired private RaceSpecificResultRepository      resultRepo;

    @GetMapping
    public String show(Model model) {
        // race_entry から今後 21日以内のレース一覧を取得
        List<Object[]> upcoming = entryRepo.findDistinctRaces();

        LocalDate today = LocalDate.now();
        LocalDate limit = today.plusDays(21);

        // 分析済みレース名の集合
        List<String> analyzedNames = patternRepo.findAllRaceNames();

        List<Map<String, Object>> events = new ArrayList<>();
        for (Object[] row : upcoming) {
            // [race_name, race_date, race_category, distance, surface, venue]
            String    raceName    = row[0] != null ? row[0].toString() : "";
            LocalDate raceDate    = row[1] != null ? LocalDate.parse(row[1].toString()) : null;
            String    category    = row[2] != null ? row[2].toString() : "";
            Object    distObj     = row[3];
            String    surface     = row[4] != null ? row[4].toString() : "";
            String    venue       = row[5] != null ? row[5].toString() : "";

            if (raceDate == null) continue;
            // 過去 3日〜未来 21日 のみ表示
            if (raceDate.isBefore(today.minusDays(3))) continue;
            if (raceDate.isAfter(limit)) continue;

            long daysLeft = ChronoUnit.DAYS.between(today, raceDate);
            boolean isAnalyzed = analyzedNames.stream()
                .anyMatch(n -> n.contains(raceName) || raceName.contains(n));
            boolean isPast = raceDate.isBefore(today);

            // 出走頭数を取得
            long entryCount = entryRepo.findByRaceNameOrderByHorseNumber(raceName).size();

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
        model.addAttribute("analyzedCount", analyzedNames.size());
        model.addAttribute("totalEvents",   events.size());

        return "calendar/index";
    }
}
