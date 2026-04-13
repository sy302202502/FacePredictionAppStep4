package com.faceprediction.config;

import java.nio.file.Paths;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * WebMvcConfig クラス
 *
 * Spring MVC のリソースハンドラをカスタマイズする設定クラス。
 * 
 * 役割:
 *   - プロジェクト内に保存された「uploads」フォルダを
 *     Web上からアクセス可能な静的リソースとして公開する。
 *   - 例: http://localhost:8080/uploads/ファイル名 でアクセス可能になる。
 */
@Configuration  // Spring の設定クラスとして登録される
public class WebMvcConfig implements WebMvcConfigurer {

    /**
     * 静的リソースのマッピングを追加する。
     * 
     * @param registry ResourceHandlerRegistry: 静的リソースのマッピングを管理するオブジェクト
     */
    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        // ~/faceapp/uploads（既存パス）
        String uploadPath = Paths.get(System.getProperty("user.home"), "faceapp", "uploads")
                                 .toUri()
                                 .toString();

        // プロジェクト直下の uploads（馬写真など）
        String projectUploadPath = Paths.get(System.getProperty("user.dir"), "uploads")
                                        .toUri()
                                        .toString();

        registry.addResourceHandler("/uploads/**")
                .addResourceLocations(uploadPath, projectUploadPath)
                .setCachePeriod(3600);

        // classpath内の静的リソース（CSS・JS・画像など）を明示的に公開
        registry.addResourceHandler("/css/**")
                .addResourceLocations("classpath:/static/css/");
        registry.addResourceHandler("/js/**")
                .addResourceLocations("classpath:/static/js/");
        registry.addResourceHandler("/images/**")
                .addResourceLocations("classpath:/static/images/");
    }
}
