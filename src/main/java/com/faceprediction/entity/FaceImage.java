package com.faceprediction.entity;

import javax.persistence.Column;
import javax.persistence.Entity;
import javax.persistence.GeneratedValue;
import javax.persistence.GenerationType;
import javax.persistence.Id;

/**
 * FaceImage エンティティ
 *
 * データベースに保存される「顔画像と関連情報」を表すクラス。
 * 
 * 主なカラム:
 *   - id: 主キー
 *   - horseName: 馬の名前
 *   - trackCondition: 馬場状態
 *   - imagePath: 保存された画像のパス（Webアクセス用の相対パス）
 *   - score: 予測スコアなどを格納する数値（NOT NULL 制約あり）
 */
@Entity  // JPAによってテーブルとマッピングされることを示す
public class FaceImage {

    /** 主キー (AUTO_INCREMENT 相当) */
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 馬の名前（例: サクラバクシンオー） */
    private String horseName;

    /** 馬場状態（例: 良、不良、稍重など） */
    private String trackCondition;

    /** 保存された画像のパス（例: /uploads/xxxx-uuid.png） */
    private String imagePath;

    /**
     * スコア（解析結果などを保存するための数値）
     * - NOT NULL 制約を持つため、必ず値をセットする必要がある
     * - 初期値は 0
     */
    @Column(nullable = false)
    private int score;

    // --- コンストラクタ ---
    public FaceImage() {
        // デフォルトコンストラクタ（JPAで必須）
    }

    /**
     * 新規作成用コンストラクタ
     *
     * @param horseName 馬の名前
     * @param trackCondition 馬場状態
     * @param imagePath 保存画像のパス
     */
    public FaceImage(String horseName, String trackCondition, String imagePath) {
        this.horseName = horseName;
        this.trackCondition = trackCondition;
        this.imagePath = imagePath;
        this.score = 0;  // 初期スコアを0に設定（DB制約対応）
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
