package com.faceprediction.service;

import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import com.faceprediction.entity.FaceImage;
import com.faceprediction.repository.FaceImageRepository;

@Service
public class FaceImageService {

    private final FaceImageRepository faceImageRepository;

    @Autowired
    public FaceImageService(FaceImageRepository faceImageRepository) {
        this.faceImageRepository = faceImageRepository;
    }

    public List<FaceImage> findAll() {
        return faceImageRepository.findAll();
    }

    public FaceImage save(FaceImage faceImage) {
        return faceImageRepository.save(faceImage);
    }

    public List<FaceImage> findByHorseName(String horseName) {
        return faceImageRepository.findByHorseName(horseName);
    }

    public List<FaceImage> findByTrackCondition(String trackCondition) {
        return faceImageRepository.findByTrackCondition(trackCondition);
    }

    public List<FaceImage> findByHorseNameAndTrackCondition(String horseName, String trackCondition) {
        return faceImageRepository.findByHorseNameAndTrackCondition(horseName, trackCondition);
    }
}