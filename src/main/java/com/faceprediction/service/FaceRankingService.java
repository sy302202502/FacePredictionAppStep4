package com.faceprediction.service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Service;

import com.faceprediction.entity.RaceSpecificResult;

/**
 * /predict-v2 の「鬼眼スコア」順位付け。
 * 予想画面・買い目・答え合わせ画面で同じ順位（◎○▲…）を使うため、
 * コントローラから切り出して共通化している。
 */
@Service
public class FaceRankingService {

    // 顔面スコアと統計スコアの配合比率。
    // 2026-09-28 に本番347レースで検証し、顔面75%→50% に変更（◎の3着内率 38.6%→41.8%）。
    // 顔面は看板として半分を担う。変える場合は python/column_writer.py の FACE_WEIGHT もそろえること
    private static final double FACE_WEIGHT  = 0.5;
    private static final double STATS_WEIGHT = 0.5;
    // レース内コントラスト強調係数（平均からの差を広げる）
    private static final double CONTRAST     = 1.9;
    private static final double SCORE_MIN    = 40.0;
    private static final double SCORE_MAX    = 99.0;

    /** 順位 → 予想印。画面のランクバッジと同じ対応 */
    public static String markOf(Integer rank) {
        if (rank == null) return "";
        switch (rank) {
            case 1:  return "◎";
            case 2:  return "○";
            case 3:  return "▲";
            case 4:  return "△";
            case 5:  return "注";
            case 6:  return "☆";
            default: return "×";
        }
    }

    /**
     * 顔面スコアと統計スコアを半々で合成し、レース内でコントラストを強調して
     * スコアの団子状態を解消する。顔面分析済みの馬のみ対象（未分析は末尾・スコア無し）。
     * rows には horse_name / image_path / face_comment / face_score / score /
     * horse_number / post_position（任意で actual_rank）を含めること。
     */
    /** 海外の馬か（netkeiba の horse_id が英数字。日本の馬は数字だけ） */
    static boolean isAbroadHorse(String horseId) {
        return horseId != null && !horseId.isEmpty() && !horseId.chars().allMatch(Character::isDigit);
    }

    public List<RaceSpecificResult> rank(List<Map<String, Object>> rows) {
        // 1. 各馬の合成スコアを計算
        List<RaceSpecificResult> analyzed = new ArrayList<>();
        List<RaceSpecificResult> unanalyzed = new ArrayList<>();
        List<Double> composites = new ArrayList<>();
        // 同点時の並びを決定的にするため、クリップ前の合成スコアを覚えておく
        Map<RaceSpecificResult, Double> rawComposite = new IdentityHashMap<>();

        // 写真が無く鬼眼で見られない海外馬（horse_id が英数字）は、顔の点数の代わりにレース内で
        // 顔面分析できた馬の平均を使い、統計の点数で比べる（顔の分だけ不利にならないように）
        double faceMean = rows.stream().map(x -> x.get("face_score")).filter(java.util.Objects::nonNull)
            .mapToDouble(x -> ((Number) x).doubleValue()).average().orElse(Double.NaN);

        for (Map<String, Object> row : rows) {
            RaceSpecificResult r = new RaceSpecificResult();
            r.setHorseName((String) row.get("horse_name"));
            r.setHorseId((String) row.get("horse_id"));
            r.setImagePath((String) row.get("image_path"));
            r.setComment(toHeadlineFormat((String) row.get("face_comment")));
            Object hn = row.get("horse_number");
            if (hn != null) r.setHorseNumber(((Number) hn).intValue());
            Object pp = row.get("post_position");
            if (pp != null) r.setPostPosition(((Number) pp).intValue());
            Object ar = row.get("actual_rank");
            if (ar != null) r.setActualRank(((Number) ar).intValue());

            Object fs = row.get("face_score");
            boolean noPhotoAbroad = fs == null && isAbroadHorse(r.getHorseId()) && !Double.isNaN(faceMean)
                && row.get("score") != null;
            if (fs == null && !noPhotoAbroad) {
                r.setScore(null);
                unanalyzed.add(r);
                continue;
            }
            if (noPhotoAbroad) r.setComment("写真がないため鬼眼の対象外（統計で評価）");
            double face  = noPhotoAbroad ? faceMean : ((Number) fs).doubleValue();
            Object ss = row.get("score");
            double stats = ss != null ? ((Number) ss).doubleValue() : face;
            double composite = face * FACE_WEIGHT + stats * STATS_WEIGHT;
            r.setScore(composite); // 一旦合成スコアを格納（後で引き伸ばす）
            rawComposite.put(r, composite);
            analyzed.add(r);
            composites.add(composite);
        }

        // 2. レース内平均を基準にコントラストを強調して引き伸ばす
        if (!composites.isEmpty()) {
            double mean = composites.stream().mapToDouble(Double::doubleValue).average().orElse(70.0);
            for (RaceSpecificResult r : analyzed) {
                double stretched = mean + (r.getScore() - mean) * CONTRAST;
                stretched = Math.max(SCORE_MIN, Math.min(SCORE_MAX, stretched));
                r.setScore(Math.round(stretched * 10.0) / 10.0);
            }
        }

        // 3. スコア降順に並べ替え、順位を振り直す（未分析馬は末尾）。
        //    40/99点のクリップや丸めで同点になった場合は、クリップ前の合成スコア → 馬番の順で
        //    決める（SQLの返却順に任せると、アクセスのたびに◎や買い目が入れ替わり得る）
        Comparator<RaceSpecificResult> order = Comparator
            .comparing(RaceSpecificResult::getScore, Comparator.reverseOrder())
            .thenComparing(r -> rawComposite.get(r), Comparator.reverseOrder())
            .thenComparing(RaceSpecificResult::getHorseNumber, Comparator.nullsLast(Comparator.naturalOrder()))
            .thenComparing(RaceSpecificResult::getHorseName, Comparator.nullsLast(Comparator.naturalOrder()));
        analyzed.sort(order);
        List<RaceSpecificResult> results = new ArrayList<>();
        results.addAll(analyzed);
        results.addAll(unanalyzed);
        int rank = 1;
        for (RaceSpecificResult r : results) {
            r.setRankPosition(rank++);
        }
        return results;
    }

    /**
     * face_comment（「phrase1。phrase2。総括」形式）を
     * テンプレートの見出し分割（全角スペース区切り）に合わせて変換する。
     * 先頭の「。」を全角スペースに置換し、1文目を見出し、残りを本文にする。
     */
    private static String toHeadlineFormat(String comment) {
        if (comment == null || comment.isBlank()) return null;
        return comment.replaceFirst("。", "　");
    }
}
