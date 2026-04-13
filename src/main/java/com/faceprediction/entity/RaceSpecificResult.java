package com.faceprediction.entity;

import java.time.LocalDateTime;

import javax.persistence.Column;
import javax.persistence.Entity;
import javax.persistence.GeneratedValue;
import javax.persistence.GenerationType;
import javax.persistence.Id;
import javax.persistence.Table;

@Entity
@Table(name = "race_specific_result")
public class RaceSpecificResult {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String raceName;
    private String horseName;
    private String horseId;
    private String imagePath;
    private Integer rankPosition;
    private Double score;
    private Integer confidenceLevel;

    @Column(columnDefinition = "TEXT")
    private String comment;

    @Column(columnDefinition = "TEXT")
    private String featureJson;

    private String dataSource;
    private LocalDateTime createdAt;

    public RaceSpecificResult() {}

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }

    public String getRaceName() { return raceName; }
    public void setRaceName(String raceName) { this.raceName = raceName; }

    public String getHorseName() { return horseName; }
    public void setHorseName(String horseName) { this.horseName = horseName; }

    public String getHorseId() { return horseId; }
    public void setHorseId(String horseId) { this.horseId = horseId; }

    public String getImagePath() { return imagePath; }
    public void setImagePath(String imagePath) { this.imagePath = imagePath; }

    public Integer getRankPosition() { return rankPosition; }
    public void setRankPosition(Integer rankPosition) { this.rankPosition = rankPosition; }

    public Double getScore() { return score; }
    public void setScore(Double score) { this.score = score; }

    public Integer getConfidenceLevel() { return confidenceLevel; }
    public void setConfidenceLevel(Integer confidenceLevel) { this.confidenceLevel = confidenceLevel; }

    public String getComment() { return comment; }
    public void setComment(String comment) { this.comment = comment; }

    public String getFeatureJson() { return featureJson; }
    public void setFeatureJson(String featureJson) { this.featureJson = featureJson; }

    public String getDataSource() { return dataSource; }
    public void setDataSource(String dataSource) { this.dataSource = dataSource; }

    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
}
