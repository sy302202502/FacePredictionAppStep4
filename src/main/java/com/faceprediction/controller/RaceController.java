package com.faceprediction.controller;

import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
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

    @GetMapping
    public String showRaceList(Model model) {
        List<Race> races = raceService.findAll();
        model.addAttribute("races", races);
        return "races/index";
    }

    @GetMapping("/new")
    public String showRaceForm(Model model) {
        model.addAttribute("race", new Race());
        return "races/form";
    }

    @PostMapping("/save")
    public String saveRace(@ModelAttribute Race race) {
        raceService.save(race);
        return "redirect:/races";
    }
}