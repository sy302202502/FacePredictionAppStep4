package com.faceprediction.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import com.faceprediction.entity.RaceEntry;

public interface RaceEntryRepository extends JpaRepository<RaceEntry, Long> {

    @Query("SELECT DISTINCT e.raceName, e.raceDate, e.raceCategory, e.distance, e.surface, e.venue FROM RaceEntry e ORDER BY e.raceDate, e.raceName")
    List<Object[]> findDistinctRaces();

    List<RaceEntry> findByRaceNameOrderByHorseNumber(String raceName);

    List<RaceEntry> findByRaceIdOrderByHorseNumber(String raceId);
}
