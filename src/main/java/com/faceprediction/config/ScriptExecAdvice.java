package com.faceprediction.config;

import java.util.concurrent.TimeUnit;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.ControllerAdvice;
import org.springframework.web.bind.annotation.ModelAttribute;

/**
 * Pythonスクリプト実行機能が使える環境かどうかを全テンプレートに公開する。
 *
 * 本番(VPS)の app コンテナは JRE のみのイメージで python3 が入っていないため、
 * 実行系のボタン（統計予想・顔面分析・週次パイプライン・万馬券厳選など）を
 * 押しても必ず失敗する。実行UIは scriptExecAvailable でガードして非表示にし、
 * 予想の生成は python コンテナ側の cron に任せる。
 */
@ControllerAdvice
public class ScriptExecAdvice {

    private static final Logger log = LoggerFactory.getLogger(ScriptExecAdvice.class);

    private static volatile Boolean pythonAvailable;

    @ModelAttribute("scriptExecAvailable")
    public boolean scriptExecAvailable() {
        return isPythonAvailable();
    }

    /** python3 が実行できる環境か（結果はキャッシュ）。コントローラの直リンクガードにも使う。 */
    public static boolean isPythonAvailable() {
        Boolean cached = pythonAvailable;
        if (cached == null) {
            synchronized (ScriptExecAdvice.class) {
                if (pythonAvailable == null) {
                    pythonAvailable = checkPython3();
                    log.info("python3 実行可否チェック: {}", pythonAvailable ? "利用可能" : "利用不可（実行UIを非表示にします）");
                }
                cached = pythonAvailable;
            }
        }
        return cached;
    }

    private static boolean checkPython3() {
        try {
            Process p = new ProcessBuilder("python3", "--version")
                    .redirectErrorStream(true)
                    .start();
            if (!p.waitFor(5, TimeUnit.SECONDS)) {
                p.destroyForcibly();
                return false;
            }
            return p.exitValue() == 0;
        } catch (Exception e) {
            return false;
        }
    }
}
