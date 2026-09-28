package com.faceprediction.controller;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;

/**
 * cron ジョブの実行履歴（管理者のみ）。
 * python/job_runner.py が job_run テーブルに記録した開始・終了・終了コード・要約を一覧する。
 */
@Controller
@RequestMapping("/jobs")
public class JobsController {

    /** job_runner のジョブ名（英字キー）→ 表示名。cron 定義は deploy/conoha_crontab.txt */
    private static final Map<String, String> LABELS = new LinkedHashMap<>();
    static {
        LABELS.put("pipeline", "週次パイプライン（毎朝9時）");
        LABELS.put("sync",     "出馬表同期（土日11・13・15時）");
        LABELS.put("odds",     "オッズ更新（土日9〜15時）");
        LABELS.put("results",  "結果取得（土日18・22時／毎朝10時）");
        LABELS.put("cleanup",  "画像整理（月曜5時）");
    }

    @Autowired private JdbcTemplate jdbc;

    @GetMapping
    public String show(Model model) {
        List<Map<String, Object>> runs;
        List<Map<String, Object>> latest;
        try {
            runs = jdbc.queryForList(
                "SELECT id, job_name, command, started_at, finished_at, exit_code, summary, " +
                "       EXTRACT(EPOCH FROM (finished_at - started_at))::int AS seconds " +
                "FROM job_run ORDER BY started_at DESC LIMIT 100");
            // ジョブごとの最新1件（ダッシュボード用）
            latest = jdbc.queryForList(
                "SELECT DISTINCT ON (job_name) job_name, started_at, finished_at, exit_code, summary " +
                "FROM job_run ORDER BY job_name, started_at DESC");
        } catch (Exception e) {
            // job_run 未作成（job_runner 経由の cron がまだ一度も動いていない）
            runs = List.of();
            latest = List.of();
        }
        model.addAttribute("runs", runs);
        model.addAttribute("latest", latest);
        model.addAttribute("labels", LABELS);
        return "jobs/index";
    }
}
