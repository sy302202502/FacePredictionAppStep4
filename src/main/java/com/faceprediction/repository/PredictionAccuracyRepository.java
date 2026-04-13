package com.faceprediction.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import com.faceprediction.entity.PredictionAccuracy;

public interface PredictionAccuracyRepository extends JpaRepository<PredictionAccuracy, Long> {

    @Query("SELECT a FROM PredictionAccuracy a"
        + " WHERE a.predictedRank = 1 AND a.top5Hit IS NOT NULL"
        + " ORDER BY a.raceDate DESC")
    List<PredictionAccuracy> findRecordedResults();

    @Query("SELECT a.raceCategory,"
        + " COUNT(DISTINCT a.raceName),"
        + " SUM(CASE WHEN a.hit = TRUE THEN 1 ELSE 0 END),"
        + " SUM(CASE WHEN a.top5Hit = TRUE THEN 1 ELSE 0 END)"
        + " FROM PredictionAccuracy a"
        + " WHERE a.predictedRank = 1 AND a.top5Hit IS NOT NULL"
        + " GROUP BY a.raceCategory"
        + " ORDER BY a.raceCategory")
    List<Object[]> findCategoryStats();

    @Query("SELECT COUNT(DISTINCT a.raceName),"
        + " SUM(CASE WHEN a.hit = TRUE THEN 1 ELSE 0 END),"
        + " SUM(CASE WHEN a.top5Hit = TRUE THEN 1 ELSE 0 END)"
        + " FROM PredictionAccuracy a"
        + " WHERE a.predictedRank = 1 AND a.top5Hit IS NOT NULL")
    List<Object[]> findOverallStats();
}
