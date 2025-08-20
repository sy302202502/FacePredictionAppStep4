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
        // プロジェクトの実行ディレクトリ直下の "uploads" フォルダを公開対象にする。
        // System.getProperty("user.dir") は実行中のプロジェクトのルートディレクトリを取得する。
        // そこに "uploads" を結合し、URI (file:/〜) に変換。
        String uploadPath = Paths.get(System.getProperty("user.dir"), "uploads")
                                 .toUri()
                                 .toString();

        // "/uploads/**" というURLパターンでアクセスされた場合に、
        // 実際の uploads フォルダにあるファイルを返すように設定。
        registry.addResourceHandler("/uploads/**")
                .addResourceLocations(uploadPath) // 実際のディレクトリの場所を指定
                .setCachePeriod(3600);            // ブラウザキャッシュ有効期限を 3600 秒（1時間）に設定（任意）

        // 実際にマッピングされるパスの例:
        // file:/C:/Users/YourName/your-project/uploads/
        // ↑ この場所にあるファイルが、http://localhost:8080/uploads/ファイル名 でアクセス可能になる。
    }
}
