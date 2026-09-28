package com.faceprediction.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import com.faceprediction.entity.RaceSpecificAccuracy;

public interface RaceSpecificAccuracyRepository extends JpaRepository<RaceSpecificAccuracy, Long> {

    /** 1着的中率を出すための集計：[totalRaces, winHits]。
     *  予想1位の行（1レース1予想につき1行）を分母・分子とも同じ単位で数える。
     *  旧実装は分母が COUNT(DISTINCT raceName) で、同名重賞が複数年あると分母だけ潰れていた */
    @Query("SELECT COUNT(a), " +
           "       SUM(CASE WHEN a.actualRank = 1 THEN 1 ELSE 0 END) " +
           "FROM RaceSpecificAccuracy a " +
           "WHERE a.predictedRank = 1")
    List<Object[]> findOverallWinStats();
}
