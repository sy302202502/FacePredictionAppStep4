package com.faceprediction.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import com.faceprediction.entity.HorseFaceFeature;

public interface HorseFaceFeatureRepository extends JpaRepository<HorseFaceFeature, Long> {

    @Query("SELECT h FROM HorseFaceFeature h WHERE h.isWinner = true AND h.noseShape IS NOT NULL ORDER BY h.winCount DESC")
    List<HorseFaceFeature> findAllWinnersWithFeatures();

    @Query("SELECT h FROM HorseFaceFeature h WHERE h.isWinner = false AND h.noseShape IS NOT NULL")
    List<HorseFaceFeature> findAllLosersWithFeatures();

    @Query("SELECT h FROM HorseFaceFeature h WHERE h.isWinner = true AND h.noseShape IS NOT NULL AND h.raceCategory = :cat ORDER BY h.winCount DESC")
    List<HorseFaceFeature> findWinnersByCategory(@Param("cat") String raceCategory);

    @Query("SELECT h FROM HorseFaceFeature h WHERE h.isWinner = false AND h.noseShape IS NOT NULL AND h.raceCategory = :cat")
    List<HorseFaceFeature> findLosersByCategory(@Param("cat") String raceCategory);

    @Query("SELECT COUNT(h) FROM HorseFaceFeature h WHERE h.isWinner = true AND h.noseShape IS NOT NULL")
    long countAnalyzedWinners();

    @Query("SELECT COUNT(h) FROM HorseFaceFeature h WHERE h.isWinner = false AND h.noseShape IS NOT NULL")
    long countAnalyzedLosers();
}
