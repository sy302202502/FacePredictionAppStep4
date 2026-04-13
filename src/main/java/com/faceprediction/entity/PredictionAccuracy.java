package com.faceprediction.entity;

import java.time.LocalDate;
import java.time.LocalDateTime;

import javax.persistence.Entity;
import javax.persistence.GeneratedValue;
import javax.persistence.GenerationType;
import javax.persistence.Id;
import javax.persistence.PrePersist;
import javax.persistence.Table;

@Entity
@Table(name = "prediction_accuracy")
public class PredictionAccuracy {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private Long predictionId;
    private String raceName;
    private LocalDate raceDate;
    private String raceCategory;
    private String horseName;
    private Integer predictedRank;
    private Integer actualRank;
    private Boolean hit;
    private Boolean top5Hit;
    private Double finalScore;
    private LocalDateTime recordedAt;

    public PredictionAccuracy() {}

    @PrePersist
    protected void onCreate() {
        if (recordedAt == null) recordedAt = LocalDateTime.now();
    }

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getPredictionId() { return predictionId; }
    public void setPredictionId(Long predictionId) { this.predictionId = predictionId; }
    public String getRaceName() { return raceName; }
    public void setRaceName(String raceName) { this.raceName = raceName; }
    public LocalDate getRaceDate() { return raceDate; }
    public void setRaceDate(LocalDate raceDate) { this.raceDate = raceDate; }
    public String getRaceCategory() { return raceCategory; }
    public void setRaceCategory(String raceCategory) { this.raceCategory = raceCategory; }
    public String getHorseName() { return horseName; }
    public void setHorseName(String horseName) { this.horseName = horseName; }
    public Integer getPredictedRank() { return predictedRank; }
    public void setPredictedRank(Integer predictedRank) { this.predictedRank = predictedRank; }
    public Integer getActualRank() { return actualRank; }
    public void setActualRank(Integer actualRank) { this.actualRank = actualRank; }
    public Boolean getHit() { return hit; }
    public void setHit(Boolean hit) { this.hit = hit; }
    public Boolean getTop5Hit() { return top5Hit; }
    public void setTop5Hit(Boolean top5Hit) { this.top5Hit = top5Hit; }
    public Double getFinalScore() { return finalScore; }
    public void setFinalScore(Double finalScore) { this.finalScore = finalScore; }
    public LocalDateTime getRecordedAt() { return recordedAt; }
    public void setRecordedAt(LocalDateTime recordedAt) { this.recordedAt = recordedAt; }
}
