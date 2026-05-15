package com.faceprediction.controller;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;

import com.faceprediction.repository.HorseFaceFeatureRepository;
import com.faceprediction.repository.PredictionAccuracyRepository;
import com.faceprediction.repository.PredictionResultRepository;
import com.faceprediction.repository.RaceEntryRepository;
import com.faceprediction.repository.RaceSpecificAccuracyRepository;
import com.faceprediction.repository.RaceSpecificPredictionRepository;
import com.faceprediction.repository.RaceSpecificResultRepository;

import java.util.List;

@Controller
public class HomeController {

    @Autowired private HorseFaceFeatureRepository featureRepo;
    @Autowired private PredictionResultRepository predictionRepo;
    @Autowired private PredictionAccuracyRepository accuracyRepo;
    @Autowired private RaceEntryRepository entryRepo;
    @Autowired private RaceSpecificResultRepository specificResultRepo;
    @Autowired private RaceSpecificPredictionRepository specificPredictionRepo;
    @Autowired private RaceSpecificAccuracyRepository specificAccuracyRepo;

    @GetMapping("/")
    public String index(Model model) {
        // ── 顔分析済み（旧システム + 新システム両方カウント）──
        long oldAnalyzedWinners = featureRepo.countAnalyzedWinners();
        long oldAnalyzedLosers  = featureRepo.countAnalyzedLosers();
        long newAnalyzed        = specificResultRepo.count();  // race_specific_result
        long totalAnalyzed      = oldAnalyzedWinners + oldAnalyzedLosers + newAnalyzed;

        // ── 予想レコード数（旧 prediction_result + 新 race_specific_prediction）──
        long oldPredictions = predictionRepo.count();
        long newPredictions = specificPredictionRepo.count();
        long totalPredictions = oldPredictions + newPredictions;

        // ── 出走馬レコード ──
        long totalEntries = entryRepo.count();

        // ── 的中率（旧 + 新の合算）──
        List<Object[]> overallList = accuracyRepo.findOverallStats();
        Object[] overall = overallList.isEmpty() ? new Object[]{0L, 0L, 0L} : overallList.get(0);
        long oldRaces = overall[0] != null ? ((Number) overall[0]).longValue() : 0;
        long oldWins  = overall[1] != null ? ((Number) overall[1]).longValue() : 0;

        List<Object[]> specificStatsList = specificAccuracyRepo.findOverallWinStats();
        long newRaces = 0;
        long newWins = 0;
        if (specificStatsList != null && !specificStatsList.isEmpty()) {
            Object[] specificStats = specificStatsList.get(0);
            if (specificStats != null && specificStats.length >= 2) {
                newRaces = specificStats[0] != null ? ((Number) specificStats[0]).longValue() : 0;
                newWins  = specificStats[1] != null ? ((Number) specificStats[1]).longValue() : 0;
            }
        }

        long totalRaces = oldRaces + newRaces;
        long winHits    = oldWins + newWins;
        double winHitRate = totalRaces > 0 ? Math.round(winHits * 1000.0 / totalRaces) / 10.0 : 0.0;

        model.addAttribute("analyzedWinners",  oldAnalyzedWinners);
        model.addAttribute("analyzedLosers",   oldAnalyzedLosers + newAnalyzed);
        model.addAttribute("totalAnalyzed",    totalAnalyzed);
        model.addAttribute("totalPredictions", totalPredictions);
        model.addAttribute("totalEntries",     totalEntries);
        model.addAttribute("totalRaces",       totalRaces);
        model.addAttribute("winHitRate",       winHitRate);

        return "index";
    }
}
