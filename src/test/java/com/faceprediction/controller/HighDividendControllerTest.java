package com.faceprediction.controller;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.sql.Date;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.dao.DataRetrievalFailureException;
import org.springframework.jdbc.BadSqlGrammarException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;

/** 万馬券チャレンジ: 今日の選定か・予想画面ができているかを返す */
@WebMvcTest(controllers = HighDividendController.class,
            properties = {"app.password=test-only-pw", "python.script.dir=/tmp"})
class HighDividendControllerTest {

    @Autowired private MockMvc mvc;
    @MockBean private JdbcTemplate jdbc;

    private Map<String, Object> row(LocalDate day, boolean ready) {
        Map<String, Object> r = new HashMap<>();
        r.put("race_name", "飛翼特別");
        r.put("race_id", "202604040210");
        r.put("venue", "新潟");
        r.put("race_date", Date.valueOf(day));
        r.put("race_number", 10);
        r.put("horse_count", 18);
        r.put("favorite_odds", 5.8);
        r.put("chaos_score", 108.8);
        r.put("candidate_count", 14);
        r.put("prediction_ready", ready);
        return r;
    }

    @Test
    void 今日の選定は日付とレース番号つきで返す() throws Exception {
        LocalDate today = LocalDate.now(ZoneId.of("Asia/Tokyo"));
        when(jdbc.queryForList(anyString())).thenReturn(List.of(row(today, true)));
        mvc.perform(get("/high-dividend/result"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.today").value(true))
            .andExpect(jsonPath("$.raceDate").value(today.toString()))
            .andExpect(jsonPath("$.raceNumber").value(10))
            .andExpect(jsonPath("$.raceId").value("202604040210"))
            .andExpect(jsonPath("$.predictionReady").value(true));
    }

    @Test
    void 前回の選定は今日ではないと返し_予想未作成なら準備中() throws Exception {
        LocalDate day = LocalDate.now(ZoneId.of("Asia/Tokyo")).minusDays(6);
        when(jdbc.queryForList(anyString())).thenReturn(List.of(row(day, false)));
        mvc.perform(get("/high-dividend/result"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.today").value(false))
            .andExpect(jsonPath("$.predictionReady").value(false));
    }

    @Test
    void 新しい列がまだ無いDBでも以前の行を返す() throws Exception {
        Map<String, Object> old = new HashMap<>();
        old.put("race_name", "新潟2歳S");
        old.put("race_id", "202604030207");
        old.put("race_date", Date.valueOf(LocalDate.of(2026, 8, 23)));
        when(jdbc.queryForList(anyString()))
            .thenThrow(new BadSqlGrammarException("select", "SELECT", new java.sql.SQLException("column does not exist")))
            .thenReturn(List.of(old));
        mvc.perform(get("/high-dividend/result"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.raceName").value("新潟2歳S"))
            .andExpect(jsonPath("$.today").value(false))
            .andExpect(jsonPath("$.predictionReady").doesNotExist());
    }

    @Test
    void テーブルが無ければ空で返す() throws Exception {
        when(jdbc.queryForList(anyString()))
            .thenThrow(new BadSqlGrammarException("select", "SELECT", new java.sql.SQLException("relation does not exist")));
        mvc.perform(get("/high-dividend/result"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$").isEmpty());
    }

    @Test
    void DB障害は空にせずエラーで返す() throws Exception {
        when(jdbc.queryForList(anyString())).thenThrow(new DataRetrievalFailureException("connection refused"));
        mvc.perform(get("/high-dividend/result")).andExpect(status().is5xxServerError());
    }
}
