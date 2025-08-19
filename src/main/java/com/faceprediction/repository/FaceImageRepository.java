package com.faceprediction.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

import com.faceprediction.entity.FaceImage;

public interface FaceImageRepository extends JpaRepository<FaceImage, Long> {

    List<FaceImage> findByHorseName(String horseName);

    List<FaceImage> findByTrackCondition(String trackCondition);

    List<FaceImage> findByHorseNameAndTrackCondition(String horseName, String trackCondition);
}