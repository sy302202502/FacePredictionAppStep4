package com.faceprediction.controller;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import com.faceprediction.entity.RaceOdds;
import com.faceprediction.entity.RaceSpecificPrediction;
import com.faceprediction.entity.RaceSpecificResult;
import com.faceprediction.repository.RaceOddsRepository;
import com.faceprediction.repository.RaceSpecificPredictionRepository;
import com.faceprediction.repository.RaceSpecificResultRepository;

@Controller
@RequestMapping("/predict-v2")
public class RacePredictionV2Controller {

    @Autowired private RaceSpecificPredictionRepository patternRepo;
    @Autowired private RaceSpecificResultRepository     resultRepo;
    @Autowired private RaceOddsRepository               oddsRepo;

    @GetMapping
    public String show(@RequestParam(required = false) String raceName, Model model) {

        List<String> raceNames = patternRepo.findAllRaceNames();
        model.addAttribute("raceNames", raceNames);

        // 選択中のレースまたは最新レース
        String selected = raceName;
        if (selected == null && !raceNames.isEmpty()) {
            selected = raceNames.get(0);
        }
        model.addAttribute("selectedRace", selected);

        if (selected != null) {
            Optional<RaceSpecificPrediction> patternOpt = patternRepo.findFirstByRaceNameOrderByAnalyzedAtDesc(selected);
            patternOpt.ifPresent(p -> {
                model.addAttribute("pattern", p);
                // 信頼度を星文字列に変換
                int lv = p.getConfidenceLevel() != null ? p.getConfidenceLevel() : 3;
                model.addAttribute("confidenceStars", "★".repeat(lv) + "☆".repeat(5 - lv));
            });

            List<RaceSpecificResult> results = resultRepo.findByRaceNameOrderByRankPosition(selected);
            model.addAttribute("results", results);

            // オッズデータ（馬名→RaceOdds）。レース当日以外は空マップになる
            List<RaceOdds> oddsList = oddsRepo.findByRaceNameOrderByPopularityAsc(selected);
            Map<String, RaceOdds> oddsMap = oddsList.stream()
                .collect(Collectors.toMap(RaceOdds::getHorseName, o -> o, (a, b) -> a));
            model.addAttribute("oddsMap", oddsMap);
        } else {
            model.addAttribute("results", List.of());
            model.addAttribute("oddsMap", Map.of());
        }

        return "prediction/v2";
    }
}
