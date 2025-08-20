package com.faceprediction.entity;

import java.time.LocalDate;

import javax.persistence.Entity;
import javax.persistence.GeneratedValue;
import javax.persistence.GenerationType;
import javax.persistence.Id;
import javax.persistence.Table;

import org.springframework.format.annotation.DateTimeFormat;

@Entity
@Table(name = "races")
public class Race {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String raceName;

    private String location;

    private int distance;

    private String trackCondition;

    @DateTimeFormat(pattern = "yyyy-MM-dd") // ← 追加：日付変換用
    private LocalDate date;

    // デフォルトコンストラクタ
    public Race() {}

    // 全項目を引数に取るコンストラクタ
    public Race(String raceName, String location, int distance, String trackCondition, LocalDate date) {
        this.raceName = raceName;
        this.location = location;
        this.distance = distance;
        this.trackCondition = trackCondition;
        this.date = date;
    }

    // Getter & Setter
    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getRaceName() {
        return raceName;
    }

    public void setRaceName(String raceName) {
        this.raceName = raceName;
    }

    public String getLocation() {
        return location;
    }

    public void setLocation(String location) {
        this.location = location;
    }

    public int getDistance() {
        return distance;
    }

    public void setDistance(int distance) {
        this.distance = distance;
    }

    public String getTrackCondition() {
        return trackCondition;
    }

    public void setTrackCondition(String trackCondition) {
        this.trackCondition = trackCondition;
    }

    public LocalDate getDate() {
        return date;
    }

    public void setDate(LocalDate date) {
        this.date = date;
    }
}