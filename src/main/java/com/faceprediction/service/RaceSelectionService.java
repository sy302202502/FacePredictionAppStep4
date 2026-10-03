package com.faceprediction.service;

import java.util.List;
import java.util.Map;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

/**
 * 予想画面・統計予想・週次画面の「どの開催を表示するか」を決める。
 *
 * 以前はレース名で選んでいたため、同名重賞が複数年そろうと前年の予想を選べず、
 * 表示は常に「同名の最新開催」になっていた。選択肢も表示も開催（race_id）単位にする。
 * 旧来の ?raceName= 形式のリンク（Discord 通知など）は、その名前の最新開催として受け付ける。
 */
@Service
public class RaceSelectionService {

    @Autowired private JdbcTemplate jdbc;

    /** 予想のある開催の一覧（新しく予想した順）。各要素: race_id / race_name / race_date / label */
    public List<Map<String, Object>> listRaces() {
        return jdbc.queryForList(
            "SELECT sp.race_id, MIN(re.race_name) AS race_name, MAX(re.race_date) AS race_date, " +
            "       TO_CHAR(MAX(re.race_date), 'MM/DD') || '　' || MIN(re.race_name) AS label " +
            "FROM stats_prediction sp " +
            "JOIN race_entry re ON re.race_id = sp.race_id AND re.horse_id = sp.horse_id " +
            "WHERE sp.race_id IS NOT NULL " +
            "GROUP BY sp.race_id " +
            "ORDER BY MAX(sp.created_at) DESC, sp.race_id DESC");
    }

    /**
     * 表示する開催を決める。raceId が一覧にあればそれ、raceName ならその名前の最新開催、
     * どちらも無ければ一覧の先頭。該当なしは null。
     */
    public String resolve(String raceId, String raceName, List<Map<String, Object>> races) {
        if (raceId != null && races.stream().anyMatch(r -> raceId.equals(r.get("race_id")))) {
            return raceId;
        }
        if (raceName != null && !raceName.isBlank()) {
            List<String> ids = jdbc.queryForList(
                "SELECT re.race_id FROM race_entry re " +
                "WHERE re.race_name = ? AND EXISTS (SELECT 1 FROM stats_prediction sp WHERE sp.race_id = re.race_id) " +
                "ORDER BY re.race_date DESC, re.race_id DESC LIMIT 1",
                String.class, raceName);
            if (!ids.isEmpty()) return ids.get(0);
        }
        return races.isEmpty() ? null : (String) races.get(0).get("race_id");
    }

    /** 開催のレース名（表示・既存JSのキー用） */
    public String nameOf(String raceId, List<Map<String, Object>> races) {
        return races.stream()
            .filter(r -> raceId != null && raceId.equals(r.get("race_id")))
            .map(r -> (String) r.get("race_name"))
            .findFirst().orElse(null);
    }

    /**
     * 一覧を作らずに1開催だけ解決する（配信オーバーレイなど毎分アクセスされる画面用）。
     * raceId が予想のある開催ならそれ、raceName ならその名前の最新開催、無ければ最新の開催。
     * 戻り値: {race_id, race_name} / 該当なしは null
     */
    public Map<String, Object> resolveOne(String raceId, String raceName) {
        String sql =
            "SELECT sp.race_id, MIN(re.race_name) AS race_name FROM stats_prediction sp " +
            "JOIN race_entry re ON re.race_id = sp.race_id AND re.horse_id = sp.horse_id ";
        List<Map<String, Object>> rows;
        if (raceId != null && raceId.matches("\\d{4}[0-9A-Z]{8}")) {
            rows = jdbc.queryForList(sql + "WHERE sp.race_id = ? GROUP BY sp.race_id", raceId);
            if (!rows.isEmpty()) return rows.get(0);
        }
        if (raceName != null && !raceName.isBlank()) {
            rows = jdbc.queryForList(sql + "WHERE re.race_name = ? GROUP BY sp.race_id " +
                "ORDER BY MAX(re.race_date) DESC, sp.race_id DESC LIMIT 1", raceName);
            if (!rows.isEmpty()) return rows.get(0);
        }
        rows = jdbc.queryForList(sql + "WHERE sp.race_id IS NOT NULL GROUP BY sp.race_id " +
            "ORDER BY MAX(sp.created_at) DESC, sp.race_id DESC LIMIT 1");
        return rows.isEmpty() ? null : rows.get(0);
    }
}
