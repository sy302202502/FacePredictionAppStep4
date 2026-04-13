package com.faceprediction.controller;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;

import com.faceprediction.repository.HorseFaceFeatureRepository;
import com.faceprediction.repository.PredictionAccuracyRepository;
import com.faceprediction.repository.PredictionResultRepository;
import com.faceprediction.repository.RaceEntryRepository;

import java.util.List;

@Controller
public class HomeController {

    @Autowired private HorseFaceFeatureRepository featureRepo;
    @Autowired private PredictionResultRepository predictionRepo;
    @Autowired private PredictionAccuracyRepository accuracyRepo;
    @Autowired private RaceEntryRepository entryRepo;

    @GetMapping("/")
    public String index(Model model) {
        // DB統計
        long analyzedWinners = featureRepo.countAnalyzedWinners();
        long analyzedLosers  = featureRepo.countAnalyzedLosers();
        long totalAnalyzed   = analyzedWinners + analyzedLosers;
        long totalPredictions = predictionRepo.count();
        long totalEntries    = entryRepo.count();

        // 的中率
        List<Object[]> overallList = accuracyRepo.findOverallStats();
        Object[] overall = overallList.isEmpty() ? new Object[]{0L, 0L, 0L} : overallList.get(0);
        long totalRaces = overall[0] != null ? ((Number) overall[0]).longValue() : 0;
        long winHits    = overall[1] != null ? ((Number) overall[1]).longValue() : 0;
        double winHitRate = totalRaces > 0 ? Math.round(winHits * 1000.0 / totalRaces) / 10.0 : 0.0;

        model.addAttribute("analyzedWinners",  analyzedWinners);
        model.addAttribute("analyzedLosers",   analyzedLosers);
        model.addAttribute("totalAnalyzed",    totalAnalyzed);
        model.addAttribute("totalPredictions", totalPredictions);
        model.addAttribute("totalEntries",     totalEntries);
        model.addAttribute("totalRaces",       totalRaces);
        model.addAttribute("winHitRate",       winHitRate);

        return "index";
    }
}
