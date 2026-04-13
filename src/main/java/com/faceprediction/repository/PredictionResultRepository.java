package com.faceprediction.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import com.faceprediction.entity.PredictionResult;

public interface PredictionResultRepository extends JpaRepository<PredictionResult, Long> {

    @Query("SELECT DISTINCT p.targetRaceName FROM PredictionResult p ORDER BY p.targetRaceName")
    List<String> findDistinctRaceNames();

    List<PredictionResult> findByTargetRaceNameOrderByRankPosition(String raceName);

    @Query("SELECT p FROM PredictionResult p ORDER BY p.createdAt DESC")
    List<PredictionResult> findLatestResults();
}
