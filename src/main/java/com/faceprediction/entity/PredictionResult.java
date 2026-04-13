package com.faceprediction.entity;

import java.time.LocalDate;
import java.time.LocalDateTime;

import javax.persistence.Column;
import javax.persistence.Entity;
import javax.persistence.GeneratedValue;
import javax.persistence.GenerationType;
import javax.persistence.Id;
import javax.persistence.Table;

@Entity
@Table(name = "prediction_result")
public class PredictionResult {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String targetRaceName;
    private LocalDate targetRaceDate;
    private String raceCategory;
    private String horseName;
    private String horseId;
    private String imagePath;
    private Double similarityScore;
    private Double diffScore;
    private Double finalScore;
    private Integer rankPosition;

    @Column(columnDefinition = "TEXT")
    private String analysisDetail;

    private LocalDateTime createdAt;

    public PredictionResult() {}

    // Getters & Setters
    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }

    public String getTargetRaceName() { return targetRaceName; }
    public void setTargetRaceName(String targetRaceName) { this.targetRaceName = targetRaceName; }

    public LocalDate getTargetRaceDate() { return targetRaceDate; }
    public void setTargetRaceDate(LocalDate targetRaceDate) { this.targetRaceDate = targetRaceDate; }

    public String getRaceCategory() { return raceCategory; }
    public void setRaceCategory(String raceCategory) { this.raceCategory = raceCategory; }

    public String getHorseName() { return horseName; }
    public void setHorseName(String horseName) { this.horseName = horseName; }

    public String getHorseId() { return horseId; }
    public void setHorseId(String horseId) { this.horseId = horseId; }

    public String getImagePath() { return imagePath; }
    public void setImagePath(String imagePath) { this.imagePath = imagePath; }

    public Double getSimilarityScore() { return similarityScore; }
    public void setSimilarityScore(Double similarityScore) { this.similarityScore = similarityScore; }

    public Double getDiffScore() { return diffScore; }
    public void setDiffScore(Double diffScore) { this.diffScore = diffScore; }

    public Double getFinalScore() { return finalScore; }
    public void setFinalScore(Double finalScore) { this.finalScore = finalScore; }

    public Integer getRankPosition() { return rankPosition; }
    public void setRankPosition(Integer rankPosition) { this.rankPosition = rankPosition; }

    public String getAnalysisDetail() { return analysisDetail; }
    public void setAnalysisDetail(String analysisDetail) { this.analysisDetail = analysisDetail; }

    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
}
