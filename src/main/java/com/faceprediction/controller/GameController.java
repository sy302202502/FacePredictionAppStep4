package com.faceprediction.controller;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;

/**
 * 舞鬼法師ミニゲーム。
 *
 * 「まいきーおしりビート」はブラウザ内で完結するリズムゲームで、
 * サーバ側の状態も外部リソースも持たない（BGM/SEは WebAudio 合成、
 * 譜面は難易度ごとのシード固定で JS が生成、ハイスコアは localStorage）。
 * そのためコントローラはテンプレートを返すだけでよい。
 */
@Controller
@RequestMapping("/game")
public class GameController {

    /** /game は現状ゲームが1本だけなのでリズムゲームへ送る。 */
    @GetMapping
    public String index() {
        return "redirect:/game/rhythm";
    }

    @GetMapping("/rhythm")
    public String rhythm() {
        return "game/rhythm";
    }
}
