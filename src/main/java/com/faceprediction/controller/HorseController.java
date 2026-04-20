package com.faceprediction.controller;

import java.util.List;
import java.util.stream.Collectors;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import com.faceprediction.entity.HorseFaceFeature;
import com.faceprediction.repository.HorseFaceFeatureRepository;

@Controller
@RequestMapping("/horse")
public class HorseController {

    private final HorseFaceFeatureRepository featureRepo;

    @Autowired
    public HorseController(HorseFaceFeatureRepository featureRepo) {
        this.featureRepo = featureRepo;
    }

    // 馬一覧（勝ち馬）
    @GetMapping
    public String listHorses(
            @RequestParam(required = false, defaultValue = "") String q,
            Model model) {
        List<HorseFaceFeature> horses = featureRepo.findAllWinnersWithFeatures();
        if (!q.isBlank()) {
            horses = horses.stream()
                .filter(h -> h.getHorseName() != null && h.getHorseName().contains(q))
                .collect(Collectors.toList());
        }
        model.addAttribute("horses", horses);
        model.addAttribute("q", q);
        return "horse/list";
    }

    // /horse/list → /horse にリダイレクト（誤ったURL対策）
    @GetMapping("/list")
    public String listRedirect() {
        return "redirect:/horse";
    }

    // 馬の詳細
    @GetMapping("/{id}")
    public String horseDetail(@PathVariable Long id, Model model) {
        HorseFaceFeature horse = featureRepo.findById(id).orElse(null);
        if (horse == null) return "redirect:/horse";

        // 同じ特徴を持つ類似馬（勝ち馬の中から）を検索
        List<HorseFaceFeature> similar = featureRepo.findAllWinnersWithFeatures().stream()
            .filter(h -> !h.getId().equals(id))
            .filter(h -> h.getNoseShape() != null)
            .filter(h -> {
                int match = 0;
                if (eq(h.getNoseShape(),        horse.getNoseShape()))        match++;
                if (eq(h.getEyeSize(),          horse.getEyeSize()))          match++;
                if (eq(h.getFaceContour(),       horse.getFaceContour()))      match++;
                if (eq(h.getOverallImpression(), horse.getOverallImpression())) match++;
                return match >= 3;
            })
            .limit(5)
            .collect(Collectors.toList());

        model.addAttribute("horse", horse);
        model.addAttribute("similar", similar);
        return "horse/detail";
    }

    private boolean eq(String a, String b) {
        return a != null && a.equals(b);
    }
}
