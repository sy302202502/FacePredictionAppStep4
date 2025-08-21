package com.faceprediction;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * FacePredictionApp
 *
 * アプリケーションのエントリーポイントとなるクラス。
 * 
 * @SpringBootApplication が付与されているため、
 * - @Configuration（設定クラス）
 * - @EnableAutoConfiguration（自動設定有効化）
 * - @ComponentScan（コンポーネント探索）
 * の 3 つの役割を兼ねている。
 *
 * このクラスの main メソッドから Spring Boot アプリが起動する。
 */
@SpringBootApplication
public class FacePredictionApp {

    /**
     * アプリケーションを起動するメソッド。
     * SpringApplication.run(...) によって
     * 内蔵サーバー（デフォルトでは Tomcat）が立ち上がり、
     * Spring コンテナが初期化される。
     *
     * @param args コマンドライン引数
     */
    public static void main(String[] args) {
        SpringApplication.run(FacePredictionApp.class, args);
    }
}
