package com.faceprediction.config;

import java.nio.file.Paths;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * WebMvcConfig クラス
 *
 * Spring MVC のリソースハンドラをカスタマイズする設定クラス。
 *
 * 役割:
 *   - 環境変数 UPLOAD_DIR で指定されたディレクトリ（Docker: /data/uploads）
 *     と既存のローカル開発用パス（~/faceapp/uploads, project/uploads）の
 *     全てを /uploads/** にマッピングして公開する。
 */
@Configuration
public class WebMvcConfig implements WebMvcConfigurer {

    /** application.properties の upload.dir = ${UPLOAD_DIR:~/faceapp/uploads} */
    @Value("${upload.dir:#{systemProperties['user.home']}/faceapp/uploads}")
    private String configuredUploadDir;

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        // ① 設定された upload.dir（Docker環境: /data/uploads, ローカル: ~/faceapp/uploads）
        String primaryPath = Paths.get(configuredUploadDir).toUri().toString();

        // ② プロジェクト直下の uploads（ローカル開発のフォールバック）
        String projectUploadPath = Paths.get(System.getProperty("user.dir"), "uploads")
                                        .toUri()
                                        .toString();

        // ③ ホームディレクトリ配下の faceapp/uploads（後方互換）
        String homeUploadPath = Paths.get(System.getProperty("user.home"), "faceapp", "uploads")
                                     .toUri()
                                     .toString();

        registry.addResourceHandler("/uploads/**")
                .addResourceLocations(primaryPath, projectUploadPath, homeUploadPath)
                .setCachePeriod(0);

        // 静的リソース（CSS・JS・画像）
        registry.addResourceHandler("/css/**")
                .addResourceLocations("classpath:/static/css/");
        registry.addResourceHandler("/js/**")
                .addResourceLocations("classpath:/static/js/");
        registry.addResourceHandler("/images/**")
                .addResourceLocations("classpath:/static/images/");
    }
}
