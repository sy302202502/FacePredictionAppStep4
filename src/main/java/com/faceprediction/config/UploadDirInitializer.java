package com.faceprediction.config;

import java.io.File;

import javax.annotation.PostConstruct;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class UploadDirInitializer {

    @Value("${upload.dir}")
    private String uploadDir;

    @PostConstruct
    public void init() {
        File dir = new File(uploadDir).getAbsoluteFile();
        if (!dir.exists()) {
            if (dir.mkdirs()) {
                System.out.println("✅ uploads ディレクトリを作成しました: " + dir.getAbsolutePath());
            } else {
                System.err.println("⚠️ uploads ディレクトリの作成に失敗しました");
            }
        } else {
            System.out.println("ℹ️ uploads ディレクトリは既に存在します: " + dir.getAbsolutePath());
        }
    }
}