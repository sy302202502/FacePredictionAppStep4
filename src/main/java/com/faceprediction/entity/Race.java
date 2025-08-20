package com.faceprediction.entity;

import java.time.LocalDate;

import javax.persistence.Entity;
import javax.persistence.GeneratedValue;
import javax.persistence.GenerationType;
import javax.persistence.Id;
import javax.persistence.Table;
import javax.validation.constraints.Min;
import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;
import javax.validation.constraints.Size;

import org.springframework.format.annotation.DateTimeFormat;

@Entity
@Table(name = "races")
public class Race {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @NotBlank(message = "レース名を入力してください")
    @Size(max = 100, message = "レース名は100文字以内で入力してください")
    private String raceName;

    @NotBlank(message = "開催場所を入力してください")
    @Size(max = 50, message = "開催場所は50文字以内で入力してください")
    private String location;

    @Min(value = 100, message = "距離は100m以上で入力してください")
    private int distance;

    @NotBlank(message = "馬場状態を入力してください")
    private String trackCondition;

    @NotNull(message = "開催日を入力してください")
    @DateTimeFormat(pattern = "yyyy-MM-dd") // HTMLからの受け取り用
    private LocalDate date;

    // --- コンストラクタ ---
    public Race() {}

    public Race(String raceName, String location, int distance, String trackCondition, LocalDate date) {
        this.raceName = raceName;
        this.location = location;
        this.distance = distance;
        this.trackCondition = trackCondition;
        this.date = date;
    }

    // --- Getter & Setter ---
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