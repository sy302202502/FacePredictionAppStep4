package com.faceprediction.entity;

import java.time.LocalDateTime;

import javax.persistence.Entity;
import javax.persistence.GeneratedValue;
import javax.persistence.GenerationType;
import javax.persistence.Id;
import javax.persistence.Table;

@Entity
@Table(name = "race_specific_accuracy")
public class RaceSpecificAccuracy {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    private String raceName;
    private String horseName;
    private Integer predictedRank;
    private Integer actualRank;
    private Boolean hit;
    private Boolean top5Hit;
    private Double score;
    private String dataSource;
    private LocalDateTime recordedAt;

    // Getters/Setters
    public Integer getId() { return id; }
    public void setId(Integer id) { this.id = id; }
    public String getRaceName() { return raceName; }
    public void setRaceName(String raceName) { this.raceName = raceName; }
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
    public Double getScore() { return score; }
    public void setScore(Double score) { this.score = score; }
    public String getDataSource() { return dataSource; }
    public void setDataSource(String dataSource) { this.dataSource = dataSource; }
    public LocalDateTime getRecordedAt() { return recordedAt; }
    public void setRecordedAt(LocalDateTime recordedAt) { this.recordedAt = recordedAt; }
}
