package com.faceprediction.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

import com.faceprediction.entity.RaceOdds;

public interface RaceOddsRepository extends JpaRepository<RaceOdds, Long> {

    List<RaceOdds> findByRaceNameOrderByPopularityAsc(String raceName);
}
