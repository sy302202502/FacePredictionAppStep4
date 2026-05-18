package com.faceprediction.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.authentication.builders.AuthenticationManagerBuilder;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configuration.WebSecurityConfigurerAdapter;

@Configuration
@EnableWebSecurity
public class SecurityConfig extends WebSecurityConfigurerAdapter {

    @Value("${app.username:admin}")
    private String username;

    @Value("${app.password}")
    private String password;

    @Override
    protected void configure(HttpSecurity http) throws Exception {
        http
            // CSRF: SSE/REST エンドポイントは JavaScript fetch 呼び出しのため無効化
            .csrf()
                .ignoringAntMatchers(
                    "/paddock/analyze",
                    "/script/**",
                    "/stats-predict/run", "/stats-predict/run-face",
                    "/weekly/run-pipeline",
                    "/high-dividend/run-stream",
                    "/accuracy/record", "/accuracy/record-v2",
                    "/prediction/notify", "/prediction/pdf",
                    "/entry/fetch"
                )
            .and()
            .authorizeRequests()
                // 静的リソースは認証不要
                .antMatchers("/css/**", "/js/**", "/images/**", "/uploads/**").permitAll()
                // その他は全て認証必須
                .anyRequest().authenticated()
            .and()
            .httpBasic()
                .realmName("FacePrediction Admin")
            .and()
            .formLogin().disable();
    }

    @Override
    protected void configure(AuthenticationManagerBuilder auth) throws Exception {
        auth.inMemoryAuthentication()
            .withUser(username)
            .password("{noop}" + password)
            .roles("USER");
    }
}
