package com.faceprediction.service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import com.faceprediction.entity.HorseFaceFeature;
import com.faceprediction.entity.PredictionResult;
import com.faceprediction.repository.HorseFaceFeatureRepository;
import com.faceprediction.repository.PredictionResultRepository;

@Service
public class PredictionService {

    private final HorseFaceFeatureRepository featureRepository;
    private final PredictionResultRepository predictionRepository;

    @Autowired
    public PredictionService(HorseFaceFeatureRepository featureRepository,
                              PredictionResultRepository predictionRepository) {
        this.featureRepository = featureRepository;
        this.predictionRepository = predictionRepository;
    }

    public long getAnalyzedWinnerCount() {
        return featureRepository.countAnalyzedWinners();
    }

    public long getAnalyzedLoserCount() {
        return featureRepository.countAnalyzedLosers();
    }

    public List<String> getDistinctRaceNames() {
        return predictionRepository.findDistinctRaceNames();
    }

    public List<PredictionResult> getPredictionsByRace(String raceName) {
        return predictionRepository.findByTargetRaceNameOrderByRankPosition(raceName);
    }

    public List<PredictionResult> getLatestPredictions() {
        return predictionRepository.findLatestResults();
    }

    /**
     * 勝ち馬・負け馬の統計を差分込みで返す
     * Map<特徴名, Map<"winner"/"loser"/"diff", Map<値, 出現率>>>
     */
    public Map<String, Map<String, Map<String, Double>>> buildDiffStats(String raceCategory) {
        List<HorseFaceFeature> winners = raceCategory != null
            ? featureRepository.findWinnersByCategory(raceCategory)
            : featureRepository.findAllWinnersWithFeatures();
        List<HorseFaceFeature> losers = raceCategory != null
            ? featureRepository.findLosersByCategory(raceCategory)
            : featureRepository.findAllLosersWithFeatures();

        String[][] featureDefs = {
            {"鼻の形",     "noseShape"},
            {"目の大きさ", "eyeSize"},
            {"目の形",     "eyeShape"},
            {"顔の輪郭",   "faceContour"},
            {"額の幅",     "foreheadWidth"},
            {"鼻孔の大きさ","nostrilSize"},
            {"顎のライン", "jawLine"},
            {"全体的な印象","overallImpression"},
        };

        Map<String, Map<String, Map<String, Double>>> result = new LinkedHashMap<>();

        for (String[] fd : featureDefs) {
            String label = fd[0];
            String field = fd[1];

            Map<String, Integer> winCount = new LinkedHashMap<>();
            Map<String, Integer> loseCount = new LinkedHashMap<>();
            int winTotal = 0, loseTotal = 0;

            for (HorseFaceFeature f : winners) {
                String val = getField(f, field);
                int w = f.getWinCount() != null ? f.getWinCount() : 1;
                if (val != null && !val.isBlank()) {
                    winCount.merge(val, w, Integer::sum);
                    winTotal += w;
                }
            }
            for (HorseFaceFeature f : losers) {
                String val = getField(f, field);
                if (val != null && !val.isBlank()) {
                    loseCount.merge(val, 1, Integer::sum);
                    loseTotal++;
                }
            }

            Map<String, Double> winDist = toPercent(winCount, winTotal);
            Map<String, Double> loseDist = toPercent(loseCount, loseTotal);

            // 差分: 勝ち馬% - 負け馬%（正の値が勝ち馬に特有）
            Map<String, Double> diffDist = new LinkedHashMap<>();
            for (String val : winDist.keySet()) {
                double diff = winDist.get(val) - loseDist.getOrDefault(val, 0.0);
                diffDist.put(val, Math.round(diff * 10.0) / 10.0);
            }

            Map<String, Map<String, Double>> featureStat = new LinkedHashMap<>();
            featureStat.put("winner", winDist);
            featureStat.put("loser", loseDist);
            featureStat.put("diff", diffDist);
            result.put(label, featureStat);
        }

        return result;
    }

    /** レース種別ラベルマップ */
    public Map<String, String> getCategoryLabels() {
        Map<String, String> m = new LinkedHashMap<>();
        m.put("",       "全カテゴリ");
        m.put("sprint", "短距離（〜1400m）");
        m.put("mile",   "マイル（1600〜1800m）");
        m.put("middle", "中距離（2000〜2200m）");
        m.put("long",   "長距離（2400m〜）");
        m.put("dirt",   "ダート");
        return m;
    }

    private String getField(HorseFaceFeature f, String field) {
        switch (field) {
            case "noseShape":        return f.getNoseShape();
            case "eyeSize":          return f.getEyeSize();
            case "eyeShape":         return f.getEyeShape();
            case "faceContour":      return f.getFaceContour();
            case "foreheadWidth":    return f.getForeheadWidth();
            case "nostrilSize":      return f.getNostrilSize();
            case "jawLine":          return f.getJawLine();
            case "overallImpression":return f.getOverallImpression();
            default: return null;
        }
    }

    private Map<String, Double> toPercent(Map<String, Integer> counts, int total) {
        Map<String, Double> result = new LinkedHashMap<>();
        if (total == 0) return result;
        counts.entrySet().stream()
            .sorted(Map.Entry.<String, Integer>comparingByValue().reversed())
            .forEach(e -> result.put(e.getKey(), Math.round(e.getValue() * 1000.0 / total) / 10.0));
        return result;
    }

    private void addCount(Map<String, Map<String, Integer>> map, String key, String value, int weight) {
        if (value == null || value.isBlank()) return;
        map.computeIfAbsent(key, k -> new LinkedHashMap<>())
           .merge(value, weight, Integer::sum);
    }
}
