package com.faceprediction.controller;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

import com.faceprediction.entity.RaceEntry;
import com.faceprediction.repository.RaceEntryRepository;

@Controller
@RequestMapping("/entry")
public class EntryController {

    private final RaceEntryRepository entryRepo;

    @Value("${python.script.dir}")
    private String pythonScriptDir;

    @Autowired
    public EntryController(RaceEntryRepository entryRepo) {
        this.entryRepo = entryRepo;
    }

    @GetMapping
    public String showEntries(
            @RequestParam(required = false) String raceName,
            Model model) {

        List<Object[]> races = entryRepo.findDistinctRaces();
        // Map<レース名, {date, category, distance, surface, venue}>
        List<Map<String, Object>> raceList = new ArrayList<>();
        for (Object[] r : races) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("name",     r[0]);
            m.put("date",     r[1]);
            m.put("category", r[2]);
            m.put("distance", r[3]);
            m.put("surface",  r[4]);
            m.put("venue",    r[5]);
            raceList.add(m);
        }
        model.addAttribute("raceList", raceList);

        if (raceName != null && !raceName.isBlank()) {
            List<RaceEntry> entries = entryRepo.findByRaceNameOrderByHorseNumber(raceName);
            model.addAttribute("entries", entries);
            model.addAttribute("selectedRace", raceName);

            // 予想実行フォーム用の馬リスト文字列を生成（"馬名,horse_id" 1行ずつ）
            StringBuilder sb = new StringBuilder();
            for (RaceEntry e : entries) {
                if (e.getHorseId() != null && !e.getHorseId().isBlank()) {
                    sb.append(e.getHorseName()).append(",").append(e.getHorseId()).append("\n");
                }
            }
            model.addAttribute("horseListText", sb.toString());
        } else {
            model.addAttribute("entries", List.of());
            model.addAttribute("selectedRace", "");
            model.addAttribute("horseListText", "");
        }

        return "entry/index";
    }

    // entry_fetcher.py を呼び出して出走馬を自動取得
    @PostMapping("/fetch")
    public String fetchEntries(
            @RequestParam(required = false) String query,
            RedirectAttributes ra) {

        String scriptPath = pythonScriptDir + java.io.File.separator + "entry_fetcher.py";
        StringBuilder output = new StringBuilder();
        try {
            List<String> cmd = new ArrayList<>(List.of("python3", scriptPath));
            if (query != null && !query.isBlank()) cmd.add(query);

            ProcessBuilder pb = new ProcessBuilder(cmd);
            pb.environment().put("PYTHONIOENCODING", "utf-8");
            pb.redirectErrorStream(true);
            Process proc = pb.start();
            try (BufferedReader br = new BufferedReader(
                    new InputStreamReader(proc.getInputStream(), "UTF-8"))) {
                String line;
                while ((line = br.readLine()) != null) output.append(line).append("\n");
            }
            proc.waitFor();
            ra.addFlashAttribute("success", "取得完了:\n" + output);
        } catch (Exception e) {
            ra.addFlashAttribute("error", "取得失敗: " + e.getMessage());
        }
        return "redirect:/entry";
    }
}
