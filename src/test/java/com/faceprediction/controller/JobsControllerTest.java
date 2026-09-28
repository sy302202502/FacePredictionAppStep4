package com.faceprediction.controller;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.httpBasic;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.hamcrest.Matchers.containsString;

import java.sql.Timestamp;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;

/** 実行履歴画面: 管理者のみ閲覧でき、成功・失敗・実行中を描き分ける */
@WebMvcTest(controllers = JobsController.class, properties = "app.password=test-only-pw")
class JobsControllerTest {

    @Autowired private MockMvc mvc;
    @MockBean private JdbcTemplate jdbc;

    private Map<String, Object> run(String job, Integer exit, boolean finished, String summary) {
        Map<String, Object> r = new HashMap<>();
        r.put("id", 1);
        r.put("job_name", job);
        r.put("command", job + ".py");
        r.put("started_at", Timestamp.valueOf("2026-09-28 09:00:00"));
        r.put("finished_at", finished ? Timestamp.valueOf("2026-09-28 09:12:00") : null);
        r.put("exit_code", exit);
        r.put("seconds", finished ? 720 : null);
        r.put("summary", summary);
        return r;
    }

    @Test
    void 未ログインは401() throws Exception {
        mvc.perform(get("/jobs")).andExpect(status().isUnauthorized());
    }

    @Test
    void 管理者は履歴を見られる() throws Exception {
        List<Map<String, Object>> rows = List.of(
            run("pipeline", 0, true, "RESULT:{\"success\": true}"),
            run("results", 1, true, "結果取得失敗"),
            run("sync", null, false, null));
        when(jdbc.queryForList(anyString())).thenReturn(rows);
        mvc.perform(get("/jobs").with(httpBasic("admin", "test-only-pw")))
            .andExpect(status().isOk())
            .andExpect(content().string(containsString("週次パイプライン")))
            .andExpect(content().string(containsString("失敗(1)")))
            .andExpect(content().string(containsString("実行中／中断")))
            .andExpect(content().string(containsString("12分")));
    }

    @Test
    void 履歴テーブルが無くても表示できる() throws Exception {
        when(jdbc.queryForList(anyString())).thenThrow(new RuntimeException("relation job_run does not exist"));
        mvc.perform(get("/jobs").with(httpBasic("admin", "test-only-pw")))
            .andExpect(status().isOk())
            .andExpect(content().string(containsString("まだ記録がありません")));
    }
}
