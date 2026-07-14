package com.faceprediction.config;

import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.authentication.builders.AuthenticationManagerBuilder;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configuration.WebSecurityConfigurerAdapter;

@Configuration
@EnableWebSecurity
public class SecurityConfig extends WebSecurityConfigurerAdapter {

    private static final Logger log = LoggerFactory.getLogger(SecurityConfig.class);

    @Value("${app.username:admin}")
    private String username;

    @Value("${app.password:}")
    private String password;

    @Override
    protected void configure(HttpSecurity http) throws Exception {
        http
            .csrf()
                .ignoringAntMatchers(
                    "/paddock/analyze",
                    "/script/**",
                    "/stats-predict/run", "/stats-predict/run-face",
                    "/weekly/run-pipeline",
                    "/high-dividend/run-stream",
                    "/accuracy/record", "/accuracy/record-v2",
                    "/prediction/notify",
                    "/entry/fetch"
                )
            .and()
            .authorizeRequests()
                // 静的リソース・公開ページは認証不要
                .antMatchers("/css/**", "/js/**", "/images/**", "/uploads/**").permitAll()
                // Docker healthcheck が認証なしで叩くため公開（詳細情報は show-details=when_authorized で保護）
                .antMatchers("/actuator/health").permitAll()
                .antMatchers("/", "/stats-predict", "/weekly", "/predict-v2",
                             "/calendar", "/horse", "/horse/**",
                             "/high-dividend", "/accuracy").permitAll()
                // 管理機能はADMINロール必須
                .antMatchers("/script/**", "/health/**", "/entry/**", "/paddock/**",
                             "/accuracy/record", "/accuracy/record-v2",
                             "/stats-predict/run", "/stats-predict/run-face",
                             "/weekly/run-pipeline", "/high-dividend/run-stream",
                             "/entry/fetch").hasRole("ADMIN")
                .anyRequest().authenticated()
            .and()
            .httpBasic()
                .realmName("FacePrediction Admin")
            .and()
            .formLogin().disable();
    }

    @Override
    protected void configure(AuthenticationManagerBuilder auth) throws Exception {
        // 既知のデフォルトPWをコードに残さない。APP_PASSWORD 未設定時は起動ごとの
        // ランダムPWにフォールバック（アプリは起動し続けるが、既知PWでのログインは不可能になる）。
        String effectivePassword = password;
        if (effectivePassword == null || effectivePassword.isBlank()) {
            effectivePassword = UUID.randomUUID().toString();
            log.warn("APP_PASSWORD が未設定のため、この起動限りのランダムパスワードを生成しました。"
                    + "管理機能を使うには .env に APP_PASSWORD を設定して再起動してください。");
        }
        auth.inMemoryAuthentication()
            .withUser(username)
            .password("{noop}" + effectivePassword)
            .roles("ADMIN");
    }
}
