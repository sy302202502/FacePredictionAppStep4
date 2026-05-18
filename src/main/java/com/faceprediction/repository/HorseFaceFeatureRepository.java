package com.faceprediction.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import com.faceprediction.entity.HorseFaceFeature;

public interface HorseFaceFeatureRepository extends JpaRepository<HorseFaceFeature, Long> {

    @Query("SELECT h FROM HorseFaceFeature h WHERE h.isWinner = true AND h.noseShape IS NOT NULL ORDER BY h.winCount DESC")
    List<HorseFaceFeature> findAllWinnersWithFeatures();

    @Query("SELECT h FROM HorseFaceFeature h WHERE h.isWinner = true AND h.noseShape IS NOT NULL" +
           " AND (:q = '' OR h.horseName LIKE %:q%) ORDER BY h.winCount DESC")
    List<HorseFaceFeature> findWinnersWithNameFilter(@Param("q") String q);

    @Query("SELECT h FROM HorseFaceFeature h WHERE h.isWinner = true AND h.id <> :id AND h.noseShape IS NOT NULL" +
           " AND (h.noseShape = :ns OR h.eyeSize = :es OR h.faceContour = :fc OR h.overallImpression = :oi)" +
           " ORDER BY h.winCount DESC")
    List<HorseFaceFeature> findSimilarWinners(
        @Param("id") Long id,
        @Param("ns") String noseShape,
        @Param("es") String eyeSize,
        @Param("fc") String faceContour,
        @Param("oi") String overallImpression);

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
