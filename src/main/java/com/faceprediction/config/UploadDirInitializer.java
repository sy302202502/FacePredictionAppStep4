package com.faceprediction.config;

import java.io.File;

import javax.annotation.PostConstruct;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * アップロード用ディレクトリの初期化クラス
 *
 * Spring Boot 起動時に自動的に実行され、アプリで使用する
 * アップロードフォルダ（application.properties の upload.dir で指定）を
 * 存在確認・作成する役割を持つ。
 */
@Component
public class UploadDirInitializer {

    private static final Logger log = LoggerFactory.getLogger(UploadDirInitializer.class);

    /**
     * application.properties または application.yml から
     * "upload.dir" プロパティの値を取得し、変数に注入する。
     * 例: upload.dir=uploads
     */
    @Value("${upload.dir}")
    private String uploadDir;

    /**
     * アプリケーション起動後に呼び出される初期化処理。
     * 
     * - 指定されたディレクトリが存在しない場合、新規作成する。
     * - すでに存在する場合は、その旨をログに出力する。
     */
    @PostConstruct
    public void init() {
        // 絶対パスとしてディレクトリを生成
        File dir = new File(uploadDir).getAbsoluteFile();

        // ディレクトリが存在しない場合は作成を試みる
        if (!dir.exists()) {
            if (dir.mkdirs()) {
                log.info("uploads ディレクトリを作成しました: {}", dir.getAbsolutePath());
            } else {
                log.error("uploads ディレクトリの作成に失敗しました: {}", dir.getAbsolutePath());
            }
        } else {
            log.info("uploads ディレクトリは既に存在します: {}", dir.getAbsolutePath());
        }
    }
}
