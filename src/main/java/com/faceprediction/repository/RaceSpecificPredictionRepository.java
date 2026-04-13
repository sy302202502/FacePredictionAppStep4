package com.faceprediction.repository;

import java.util.List;
import java.util.Optional;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import com.faceprediction.entity.RaceSpecificPrediction;

public interface RaceSpecificPredictionRepository extends JpaRepository<RaceSpecificPrediction, Long> {

    Optional<RaceSpecificPrediction> findByRaceName(String raceName);

    @Query("SELECT p.raceName FROM RaceSpecificPrediction p ORDER BY p.analyzedAt DESC")
    List<String> findAllRaceNames();
}
