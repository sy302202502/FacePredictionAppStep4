package com.faceprediction.service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.annotation.PostConstruct;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import com.faceprediction.entity.RaceSpecificResult;

/**
 * 予想の固定保存（prediction_snapshot）。
 *
 * 画面の◎○▲は表示のたびに stats_prediction から計算しているため、後から
 * 再予想・順位ロジックの変更があると、答え合わせの印が「当時見せた印」とずれる。
 * レース結果が記録された時点（＝発走後、予想が最後に更新された状態）の印・スコアを
 * 1度だけ保存し、以後の答え合わせは必ずこの保存内容で行う。
 */
@Service
public class SnapshotService {

    private static final Logger log = LoggerFactory.getLogger(SnapshotService.class);

    @Autowired private JdbcTemplate       jdbc;
    @Autowired private FaceRankingService rankingService;

    @PostConstruct
    void ensureTable() {
        try {
            jdbc.execute(
                "CREATE TABLE IF NOT EXISTS prediction_snapshot (" +
                "  id            SERIAL PRIMARY KEY," +
                "  race_id       VARCHAR(20) NOT NULL," +
                "  horse_id      VARCHAR(20)," +
                "  horse_name    VARCHAR(100)," +
                "  horse_number  INTEGER," +
                "  post_position INTEGER," +
                "  rank_position INTEGER NOT NULL," +
                "  score         DOUBLE PRECISION," +
                "  snapshot_at   TIMESTAMP DEFAULT NOW()," +
                "  UNIQUE (race_id, horse_id))");
        } catch (Exception e) {
            log.warn("prediction_snapshot の作成に失敗: {}", e.getMessage());
        }
    }

    /**
     * 開催の予想を返す。固定保存があればそれを、無ければ現在の予想から計算して保存してから返す。
     * 着順（actual_rank）は race_specific_accuracy から付け直す。
     */
    public List<RaceSpecificResult> rankedFor(String raceId) {
        List<RaceSpecificResult> saved = load(raceId);
        if (!saved.isEmpty()) return saved;

        List<Map<String, Object>> rows = jdbc.queryForList(
            "SELECT sp.horse_id, sp.horse_name, sp.image_path, sp.face_comment, sp.face_score, sp.score, " +
            "       re.horse_number, re.post_position, rsa.actual_rank " +
            "FROM stats_prediction sp " +
            "JOIN race_entry re ON re.race_id = sp.race_id AND re.horse_id = sp.horse_id " +
            "LEFT JOIN race_specific_accuracy rsa " +
            "  ON rsa.race_id = sp.race_id AND rsa.data_source = 'stats' AND rsa.horse_name = sp.horse_name " +
            "WHERE sp.race_id = ?",
            raceId);
        List<RaceSpecificResult> ranked = rankingService.rank(rows);
        // 顔面分析の無いレース・結果未記録のレースは固定しない
        boolean recorded = rows.stream().anyMatch(r -> r.get("actual_rank") != null);
        if (!ranked.isEmpty() && ranked.get(0).getScore() != null && recorded) {
            for (RaceSpecificResult r : ranked) {
                jdbc.update(
                    "INSERT INTO prediction_snapshot (race_id, horse_id, horse_name, horse_number, " +
                    "  post_position, rank_position, score) VALUES (?,?,?,?,?,?,?) " +
                    "ON CONFLICT (race_id, horse_id) DO NOTHING",
                    raceId, r.getHorseId(), r.getHorseName(), r.getHorseNumber(),
                    r.getPostPosition(), r.getRankPosition(), r.getScore());
            }
        }
        return ranked;
    }

    private List<RaceSpecificResult> load(String raceId) {
        List<Map<String, Object>> rows;
        try {
            rows = jdbc.queryForList(
                "SELECT ps.horse_name, ps.horse_number, ps.post_position, ps.rank_position, ps.score, " +
                "       rsa.actual_rank " +
                "FROM prediction_snapshot ps " +
                "LEFT JOIN race_specific_accuracy rsa " +
                "  ON rsa.race_id = ps.race_id AND rsa.data_source = 'stats' AND rsa.horse_name = ps.horse_name " +
                "WHERE ps.race_id = ? ORDER BY ps.rank_position",
                raceId);
        } catch (Exception e) {
            return List.of();
        }
        List<RaceSpecificResult> list = new ArrayList<>();
        for (Map<String, Object> row : rows) {
            RaceSpecificResult r = new RaceSpecificResult();
            r.setHorseName((String) row.get("horse_name"));
            if (row.get("horse_number") != null) r.setHorseNumber(((Number) row.get("horse_number")).intValue());
            if (row.get("post_position") != null) r.setPostPosition(((Number) row.get("post_position")).intValue());
            r.setRankPosition(((Number) row.get("rank_position")).intValue());
            if (row.get("score") != null) r.setScore(((Number) row.get("score")).doubleValue());
            if (row.get("actual_rank") != null) r.setActualRank(((Number) row.get("actual_rank")).intValue());
            list.add(r);
        }
        return list;
    }

    /** 払戻表 {「券種:組番」: 払戻円}。未取得なら空 */
    public Map<String, Integer> payoutsFor(String raceId) {
        Map<String, Integer> map = new HashMap<>();
        try {
            for (Map<String, Object> row : jdbc.queryForList(
                    "SELECT bet_type, combo, payout FROM race_payout WHERE race_id = ?", raceId)) {
                map.put(row.get("bet_type") + ":" + row.get("combo"), ((Number) row.get("payout")).intValue());
            }
        } catch (Exception e) {
            // race_payout 未作成（結果取得がまだ一度も走っていない環境）
        }
        return map;
    }
}
