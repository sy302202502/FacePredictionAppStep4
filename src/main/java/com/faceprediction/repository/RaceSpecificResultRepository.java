package com.faceprediction.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

import com.faceprediction.entity.RaceSpecificResult;

public interface RaceSpecificResultRepository extends JpaRepository<RaceSpecificResult, Long> {

    List<RaceSpecificResult> findByRaceNameOrderByRankPosition(String raceName);
}
