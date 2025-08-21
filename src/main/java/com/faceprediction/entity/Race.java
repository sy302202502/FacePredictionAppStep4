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

/**
 * Race エンティティ
 *
 * DBの "races" テーブルに対応し、競走（レース）の情報を管理するクラス。
 *
 * 主なカラム:
 *   - id            : 主キー
 *   - raceName      : レース名
 *   - location      : 開催場所
 *   - distance      : 距離（メートル）
 *   - trackCondition: 馬場状態（良・稍重・重・不良など）
 *   - date          : 開催日
 *
 * また、入力値に対するバリデーションアノテーションを利用して、
 * フォーム入力のチェックを自動で行う。
 */
@Entity
@Table(name = "races")  // DBテーブル名を "races" と指定
public class Race {

    /** 主キー (AUTO_INCREMENT 相当) */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** レース名（必須、最大100文字まで） */
    @NotBlank(message = "レース名を入力してください")
    @Size(max = 100, message = "レース名は100文字以内で入力してください")
    private String raceName;

    /** 開催場所（必須、最大50文字まで） */
    @NotBlank(message = "開催場所を入力してください")
    @Size(max = 50, message = "開催場所は50文字以内で入力してください")
    private String location;

    /** 距離（必須、100m以上） */
    @Min(value = 100, message = "距離は100m以上で入力してください")
    private int distance;

    /** 馬場状態（例: 良、稍重、重、不良） */
    @NotBlank(message = "馬場状態を入力してください")
    private String trackCondition;

    /** 開催日（必須、yyyy-MM-dd 形式で受け取る） */
    @NotNull(message = "開催日を入力してください")
    @DateTimeFormat(pattern = "yyyy-MM-dd") // HTMLフォームから文字列を LocalDate に変換
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
