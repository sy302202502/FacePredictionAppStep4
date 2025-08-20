package com.faceprediction.entity;

import javax.persistence.Column;
import javax.persistence.Entity;
import javax.persistence.GeneratedValue;
import javax.persistence.GenerationType;
import javax.persistence.Id;

@Entity
public class FaceImage {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String horseName;

    private String trackCondition;

    private String imagePath;

    @Column(nullable = false)
    private int score;  // NOT NULL 制約を満たすよう、初期化が必要

    // --- コンストラクタ ---
    public FaceImage() {
    }

    public FaceImage(String horseName, String trackCondition, String imagePath) {
        this.horseName = horseName;
        this.trackCondition = trackCondition;
        this.imagePath = imagePath;
        this.score = 0;  // 初期スコアを0に設定
    }

    // --- Getter / Setter ---
    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getHorseName() {
        return horseName;
    }

    public void setHorseName(String horseName) {
        this.horseName = horseName;
    }

    public String getTrackCondition() {
        return trackCondition;
    }

    public void setTrackCondition(String trackCondition) {
        this.trackCondition = trackCondition;
    }

    public String getImagePath() {
        return imagePath;
    }

    public void setImagePath(String imagePath) {
        this.imagePath = imagePath;
    }

    public int getScore() {
        return score;
    }

    public void setScore(int score) {
        this.score = score;
    }
}