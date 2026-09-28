package com.faceprediction.controller;

import static org.hamcrest.Matchers.containsString;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.httpBasic;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;

import com.faceprediction.service.FaceRankingService;
import com.faceprediction.service.RaceSelectionService;

/** 東スポ参考パネル: 管理者のみ・無効時は取得しない */
@WebMvcTest(controllers = TospoController.class,
            properties = {"app.password=test-only-pw", "TOSPO_ENABLED=0"})
class TospoControllerTest {

    @Autowired private MockMvc mvc;
    @MockBean private JdbcTemplate jdbc;
    @MockBean private RaceSelectionService selectionService;
    @MockBean private FaceRankingService rankingService;

    @Test
    void 未ログインは401() throws Exception {
        mvc.perform(get("/tospo")).andExpect(status().isUnauthorized());
    }

    @Test
    void 無効なら取得せず案内を出す() throws Exception {
        when(selectionService.listRaces()).thenReturn(List.of(Map.of("race_id", "202606040911", "label", "09/27 テスト")));
        when(selectionService.resolve(any(), any(), any())).thenReturn("202606040911");
        mvc.perform(get("/tospo").with(httpBasic("admin", "test-only-pw")))
            .andExpect(status().isOk())
            .andExpect(content().string(containsString("東スポ連携は無効です")));
    }
}
