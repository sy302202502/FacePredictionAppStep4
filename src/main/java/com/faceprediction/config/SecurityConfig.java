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
        auth.inMemoryAuthentication()
            .withUser(username)
            .password("{noop}" + password)
            .roles("ADMIN");
    }
}
