package com.faceprediction.controller;

import java.util.List;

import javax.validation.Valid;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.validation.BindingResult;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ModelAttribute;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;

import com.faceprediction.entity.Race;
import com.faceprediction.service.RaceService;

@Controller
@RequestMapping("/races")
public class RaceController {

    private final RaceService raceService;

    @Autowired
    public RaceController(RaceService raceService) {
        this.raceService = raceService;
    }

    // レース一覧表示
    @GetMapping
    public String showRaceList(Model model) {
        List<Race> races = raceService.findAll();
        model.addAttribute("races", races);
        return "races/index";
    }

    // レース登録フォーム表示
    @GetMapping("/new")
    public String showRaceForm(Model model) {
        model.addAttribute("race", new Race());
        return "races/form";
    }

    // レース保存処理（バリデーション対応）
    @PostMapping("/save")
    public String saveRace(@ModelAttribute("race") @Valid Race race,
                           BindingResult bindingResult,
                           Model model) {
        if (bindingResult.hasErrors()) {
            // 入力エラーがあればフォームに戻す
            return "races/form";
        }

        raceService.save(race);
        return "redirect:/races";
    }
}