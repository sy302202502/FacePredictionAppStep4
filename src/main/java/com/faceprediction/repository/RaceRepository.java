package com.faceprediction.repository;

import org.springframework.data.jpa.repository.JpaRepository;

import com.faceprediction.entity.Race;

public interface RaceRepository extends JpaRepository<Race, Long> {
}