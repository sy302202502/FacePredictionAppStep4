package com.faceprediction.entity;

import java.time.LocalDateTime;

import javax.persistence.Column;
import javax.persistence.Entity;
import javax.persistence.GeneratedValue;
import javax.persistence.GenerationType;
import javax.persistence.Id;
import javax.persistence.Table;

@Entity
@Table(name = "horse_face_feature")
public class HorseFaceFeature {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String horseName;
    private String horseId;
    private String imagePath;
    private Integer finishRank;
    private String raceCategory;

    // ラベル特徴
    private String noseShape;
    private String eyeSize;
    private String eyeShape;
    private String faceContour;
    private String foreheadWidth;
    private String nostrilSize;
    private String jawLine;
    private String overallImpression;

    // 数値特徴量
    private Double eyeAspectRatio;
    private Double noseWidthRatio;
    private Double faceAspectRatio;
    private Double jawStrengthScore;
    private Double overallIntensity;

    // 分析信頼度
    private Integer analysisCount;
    private Double avgConfidence;

    @Column(columnDefinition = "TEXT")
    private String rawAnalysis;

    private Boolean isWinner;
    private Integer winCount;
    private LocalDateTime createdAt;

    public HorseFaceFeature() {}

    // Getters & Setters
    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }

    public String getHorseName() { return horseName; }
    public void setHorseName(String horseName) { this.horseName = horseName; }

    public String getHorseId() { return horseId; }
    public void setHorseId(String horseId) { this.horseId = horseId; }

    public String getImagePath() { return imagePath; }
    public void setImagePath(String imagePath) { this.imagePath = imagePath; }

    public Integer getFinishRank() { return finishRank; }
    public void setFinishRank(Integer finishRank) { this.finishRank = finishRank; }

    public String getRaceCategory() { return raceCategory; }
    public void setRaceCategory(String raceCategory) { this.raceCategory = raceCategory; }

    public String getNoseShape() { return noseShape; }
    public void setNoseShape(String noseShape) { this.noseShape = noseShape; }

    public String getEyeSize() { return eyeSize; }
    public void setEyeSize(String eyeSize) { this.eyeSize = eyeSize; }

    public String getEyeShape() { return eyeShape; }
    public void setEyeShape(String eyeShape) { this.eyeShape = eyeShape; }

    public String getFaceContour() { return faceContour; }
    public void setFaceContour(String faceContour) { this.faceContour = faceContour; }

    public String getForeheadWidth() { return foreheadWidth; }
    public void setForeheadWidth(String foreheadWidth) { this.foreheadWidth = foreheadWidth; }

    public String getNostrilSize() { return nostrilSize; }
    public void setNostrilSize(String nostrilSize) { this.nostrilSize = nostrilSize; }

    public String getJawLine() { return jawLine; }
    public void setJawLine(String jawLine) { this.jawLine = jawLine; }

    public String getOverallImpression() { return overallImpression; }
    public void setOverallImpression(String overallImpression) { this.overallImpression = overallImpression; }

    public Double getEyeAspectRatio() { return eyeAspectRatio; }
    public void setEyeAspectRatio(Double eyeAspectRatio) { this.eyeAspectRatio = eyeAspectRatio; }

    public Double getNoseWidthRatio() { return noseWidthRatio; }
    public void setNoseWidthRatio(Double noseWidthRatio) { this.noseWidthRatio = noseWidthRatio; }

    public Double getFaceAspectRatio() { return faceAspectRatio; }
    public void setFaceAspectRatio(Double faceAspectRatio) { this.faceAspectRatio = faceAspectRatio; }

    public Double getJawStrengthScore() { return jawStrengthScore; }
    public void setJawStrengthScore(Double jawStrengthScore) { this.jawStrengthScore = jawStrengthScore; }

    public Double getOverallIntensity() { return overallIntensity; }
    public void setOverallIntensity(Double overallIntensity) { this.overallIntensity = overallIntensity; }

    public Integer getAnalysisCount() { return analysisCount; }
    public void setAnalysisCount(Integer analysisCount) { this.analysisCount = analysisCount; }

    public Double getAvgConfidence() { return avgConfidence; }
    public void setAvgConfidence(Double avgConfidence) { this.avgConfidence = avgConfidence; }

    public String getRawAnalysis() { return rawAnalysis; }
    public void setRawAnalysis(String rawAnalysis) { this.rawAnalysis = rawAnalysis; }

    public Boolean getIsWinner() { return isWinner; }
    public void setIsWinner(Boolean isWinner) { this.isWinner = isWinner; }

    public Integer getWinCount() { return winCount; }
    public void setWinCount(Integer winCount) { this.winCount = winCount; }

    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
}
