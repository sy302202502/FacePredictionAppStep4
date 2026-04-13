package com.faceprediction.entity;

import java.time.LocalDateTime;

import javax.persistence.Column;
import javax.persistence.Entity;
import javax.persistence.GeneratedValue;
import javax.persistence.GenerationType;
import javax.persistence.Id;
import javax.persistence.Table;

@Entity
@Table(name = "race_specific_prediction")
public class RaceSpecificPrediction {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String raceName;
    private Integer totalYears;
    private Integer totalHorses;
    private Integer top5Horses;
    private Integer bottomHorses;

    @Column(columnDefinition = "TEXT")
    private String top5PatternJson;

    @Column(columnDefinition = "TEXT")
    private String bottomPatternJson;

    @Column(columnDefinition = "TEXT")
    private String top5Comment;

    @Column(columnDefinition = "TEXT")
    private String bottomComment;

    @Column(columnDefinition = "TEXT")
    private String diffComment;

    private Integer supplementalCount;
    private Integer confidenceLevel;
    private LocalDateTime analyzedAt;

    public RaceSpecificPrediction() {}

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }

    public String getRaceName() { return raceName; }
    public void setRaceName(String raceName) { this.raceName = raceName; }

    public Integer getTotalYears() { return totalYears; }
    public void setTotalYears(Integer totalYears) { this.totalYears = totalYears; }

    public Integer getTotalHorses() { return totalHorses; }
    public void setTotalHorses(Integer totalHorses) { this.totalHorses = totalHorses; }

    public Integer getTop5Horses() { return top5Horses; }
    public void setTop5Horses(Integer top5Horses) { this.top5Horses = top5Horses; }

    public Integer getBottomHorses() { return bottomHorses; }
    public void setBottomHorses(Integer bottomHorses) { this.bottomHorses = bottomHorses; }

    public String getTop5PatternJson() { return top5PatternJson; }
    public void setTop5PatternJson(String top5PatternJson) { this.top5PatternJson = top5PatternJson; }

    public String getBottomPatternJson() { return bottomPatternJson; }
    public void setBottomPatternJson(String bottomPatternJson) { this.bottomPatternJson = bottomPatternJson; }

    public String getTop5Comment() { return top5Comment; }
    public void setTop5Comment(String top5Comment) { this.top5Comment = top5Comment; }

    public String getBottomComment() { return bottomComment; }
    public void setBottomComment(String bottomComment) { this.bottomComment = bottomComment; }

    public String getDiffComment() { return diffComment; }
    public void setDiffComment(String diffComment) { this.diffComment = diffComment; }

    public Integer getSupplementalCount() { return supplementalCount; }
    public void setSupplementalCount(Integer supplementalCount) { this.supplementalCount = supplementalCount; }

    public Integer getConfidenceLevel() { return confidenceLevel; }
    public void setConfidenceLevel(Integer confidenceLevel) { this.confidenceLevel = confidenceLevel; }

    public LocalDateTime getAnalyzedAt() { return analyzedAt; }
    public void setAnalyzedAt(LocalDateTime analyzedAt) { this.analyzedAt = analyzedAt; }
}
