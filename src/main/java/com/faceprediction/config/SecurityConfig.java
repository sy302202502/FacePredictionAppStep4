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

    /** CSRF除外を許すのは fetch(XHR) 経由のエンドポイントのみ。
     *  HTMLフォームは th:action でCSRFトークンが自動付与されるため除外不要。 */
    private static final String[] XHR_ONLY_ENDPOINTS = {
        "/paddock/analyze",
        "/script/odds-fetch", "/script/race-analyzer",
        "/stats-predict/run", "/stats-predict/run-face",
        "/weekly/run-pipeline"
        // /high-dividend/run-stream は GET(SSE) のため CSRF 対象外（除外不要）
    };

    @Override
    protected void configure(HttpSecurity http) throws Exception {
        http
            .csrf()
                // Cookieベースのトークンリポジトリを使う（セッション不要）。
                // セッション版だと、permitAll の大きなページ(/calendar等)で
                // レスポンスコミット後のセッション生成に失敗し 500 になる。
                .csrfTokenRepository(
                    org.springframework.security.web.csrf.CookieCsrfTokenRepository.withHttpOnlyFalse())
                // fetch呼び出し専用エンドポイントのみ除外（下の XhrGuardFilter が
                // X-Requested-With を必須化し、フォーム偽装CSRFを遮断する）
                .ignoringAntMatchers(XHR_ONLY_ENDPOINTS)
            .and()
            // CSRF除外パスへのPOSTは XMLHttpRequest ヘッダ必須（HTMLフォームでは付与不能。
            // クロスオリジンのfetchで付ければCORSプリフライトが走り、既定で拒否される）。
            // Basic認証の後に置き、未認証=401 / 認証済みヘッダ無し=403 と意味を分ける。
            .addFilterAfter(new XhrGuardFilter(),
                org.springframework.security.web.authentication.www.BasicAuthenticationFilter.class)
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

    /** CSRF除外パス(XHR_ONLY_ENDPOINTS)へのPOSTに X-Requested-With を要求するフィルタ。 */
    private static class XhrGuardFilter extends org.springframework.web.filter.OncePerRequestFilter {
        private final org.springframework.util.AntPathMatcher matcher =
            new org.springframework.util.AntPathMatcher();

        @Override
        protected void doFilterInternal(javax.servlet.http.HttpServletRequest req,
                                        javax.servlet.http.HttpServletResponse res,
                                        javax.servlet.FilterChain chain)
                throws javax.servlet.ServletException, java.io.IOException {
            if ("POST".equalsIgnoreCase(req.getMethod())) {
                String path = req.getServletPath();
                for (String pattern : XHR_ONLY_ENDPOINTS) {
                    if (matcher.match(pattern, path)) {
                        if (!"XMLHttpRequest".equals(req.getHeader("X-Requested-With"))) {
                            res.sendError(javax.servlet.http.HttpServletResponse.SC_FORBIDDEN,
                                          "X-Requested-With header required");
                            return;
                        }
                        break;
                    }
                }
            }
            chain.doFilter(req, res);
        }
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
