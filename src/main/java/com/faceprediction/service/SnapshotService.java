package com.faceprediction.service;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.annotation.PostConstruct;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import com.faceprediction.entity.RaceSpecificResult;

/**
 * 予想の固定保存（prediction_snapshot）。
 *
 * 画面の◎○▲は表示のたびに stats_prediction から計算しているため、後から再予想や
 * 順位ロジックの変更があると、答え合わせの印が「当時見せた印」とずれる。
 * そこで 10分おきのスケジューラで次のとおり保存し、答え合わせは保存内容で行う。
 *   ・開催当日で結果がまだ無いレース → 最新の印で上書き（＝発走前の最終状態を追いかける）
 *   ・結果が記録されたレース          → 以後は上書きしない（凍結）
 *   ・結果記録済みなのに未保存のレース → 馬番がそろっていれば1度だけ保存（取りこぼし救済）
 * 保存はレース単位の1トランザクション（全頭を入れ替える）なので、途中の状態は残らない。
 * 閲覧（GET）では保存しない。
 */
@Service
public class SnapshotService {

    private static final Logger log = LoggerFactory.getLogger(SnapshotService.class);

    @Autowired private JdbcTemplate        jdbc;
    @Autowired private FaceRankingService  rankingService;
    @Autowired private TransactionTemplate tx;

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

    /** 10分おき（起動1分後から）。多重起動しないよう fixedDelay */
    @Scheduled(initialDelay = 60_000, fixedDelay = 600_000)
    public void refresh() {
        try {
            String today = LocalDate.now().toString();  // コンテナは TZ=Asia/Tokyo
            // 当日・結果未記録 → 上書き
            for (String id : jdbc.queryForList(
                    "SELECT DISTINCT sp.race_id FROM stats_prediction sp " +
                    "JOIN race_entry re ON re.race_id = sp.race_id " +
                    "WHERE re.race_date = CAST(? AS DATE) " +
                    "  AND NOT EXISTS (SELECT 1 FROM race_specific_accuracy rsa " +
                    "                  WHERE rsa.race_id = sp.race_id AND rsa.data_source = 'stats')",
                    String.class, today)) {
                save(id, false);
            }
            // 結果記録済み・未保存 → 1度だけ（馬番がそろってから）
            for (String id : jdbc.queryForList(
                    "SELECT DISTINCT rsa.race_id FROM race_specific_accuracy rsa " +
                    "WHERE rsa.data_source = 'stats' AND rsa.race_id IS NOT NULL " +
                    "  AND NOT EXISTS (SELECT 1 FROM prediction_snapshot ps WHERE ps.race_id = rsa.race_id)",
                    String.class)) {
                save(id, true);
            }
        } catch (Exception e) {
            log.warn("予想の固定保存に失敗: {}", e.getMessage());
        }
    }

    /**
     * 開催の予想をレース単位で入れ替え保存する。
     * @param requireNumbers 買い目に使う上位5頭に馬番が欠けていれば保存しない（払戻と照合できないため）。
     *                       取消馬は馬番が付かないままなので、全頭ではなく上位5頭で判定する
     */
    void save(String raceId, boolean requireNumbers) {
        List<RaceSpecificResult> ranked = rankingService.rank(liveRows(raceId));
        if (ranked.isEmpty() || ranked.get(0).getScore() == null) return;  // 顔面分析なし
        if (requireNumbers && ranked.stream().filter(r -> r.getScore() != null).limit(5)
                .anyMatch(r -> r.getHorseNumber() == null)) return;
        tx.executeWithoutResult(status -> {
            jdbc.update("DELETE FROM prediction_snapshot WHERE race_id = ?", raceId);
            for (RaceSpecificResult r : ranked) {
                jdbc.update(
                    "INSERT INTO prediction_snapshot (race_id, horse_id, horse_name, horse_number, " +
                    "  post_position, rank_position, score) VALUES (?,?,?,?,?,?,?)",
                    raceId, r.getHorseId(), r.getHorseName(), r.getHorseNumber(),
                    r.getPostPosition(), r.getRankPosition(), r.getScore());
            }
        });
    }

    /**
     * 答え合わせ用の開催の予想。固定保存があればそれを、無ければ現在の予想から計算して返す
     * （このとき保存はしない）。着順は race_specific_accuracy から付け直す。
     */
    public List<RaceSpecificResult> rankedFor(String raceId) {
        List<RaceSpecificResult> saved = load(raceId);
        return saved.isEmpty() ? rankingService.rank(liveRows(raceId)) : saved;
    }

    private List<Map<String, Object>> liveRows(String raceId) {
        return jdbc.queryForList(
            "SELECT sp.horse_id, sp.horse_name, sp.image_path, sp.face_comment, sp.face_score, sp.score, " +
            "       re.horse_number, re.post_position, rsa.actual_rank " +
            "FROM stats_prediction sp " +
            "JOIN race_entry re ON re.race_id = sp.race_id AND re.horse_id = sp.horse_id " +
            "LEFT JOIN race_specific_accuracy rsa " +
            "  ON rsa.race_id = sp.race_id AND rsa.data_source = 'stats' AND rsa.horse_name = sp.horse_name " +
            "WHERE sp.race_id = ?",
            raceId);
    }

    private List<RaceSpecificResult> load(String raceId) {
        List<Map<String, Object>> rows;
        try {
            rows = jdbc.queryForList(
                "SELECT ps.horse_id, ps.horse_name, ps.horse_number, ps.post_position, ps.rank_position, " +
                "       ps.score, rsa.actual_rank " +
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
            r.setHorseId((String) row.get("horse_id"));
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
