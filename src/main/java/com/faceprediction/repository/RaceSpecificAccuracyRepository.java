package com.faceprediction.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import com.faceprediction.entity.RaceSpecificAccuracy;

public interface RaceSpecificAccuracyRepository extends JpaRepository<RaceSpecificAccuracy, Long> {

    /** 1着的中率を出すための集計：[totalRaces, winHits] */
    @Query("SELECT COUNT(DISTINCT a.raceName), " +
           "       SUM(CASE WHEN a.predictedRank = 1 AND a.actualRank = 1 THEN 1 ELSE 0 END) " +
           "FROM RaceSpecificAccuracy a")
    List<Object[]> findOverallWinStats();
}
