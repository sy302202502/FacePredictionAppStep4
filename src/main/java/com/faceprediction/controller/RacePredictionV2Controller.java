package com.faceprediction.controller;

import java.util.List;
import java.util.Optional;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import com.faceprediction.entity.RaceSpecificPrediction;
import com.faceprediction.entity.RaceSpecificResult;
import com.faceprediction.repository.RaceSpecificPredictionRepository;
import com.faceprediction.repository.RaceSpecificResultRepository;

@Controller
@RequestMapping("/predict-v2")
public class RacePredictionV2Controller {

    @Autowired private RaceSpecificPredictionRepository patternRepo;
    @Autowired private RaceSpecificResultRepository     resultRepo;

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
            Optional<RaceSpecificPrediction> patternOpt = patternRepo.findByRaceName(selected);
            patternOpt.ifPresent(p -> {
                model.addAttribute("pattern", p);
                // 信頼度を星文字列に変換
                int lv = p.getConfidenceLevel() != null ? p.getConfidenceLevel() : 3;
                model.addAttribute("confidenceStars", "★".repeat(lv) + "☆".repeat(5 - lv));
            });

            List<RaceSpecificResult> results = resultRepo.findByRaceNameOrderByRankPosition(selected);
            model.addAttribute("results", results);
        } else {
            model.addAttribute("results", List.of());
        }

        return "prediction/v2";
    }
}
