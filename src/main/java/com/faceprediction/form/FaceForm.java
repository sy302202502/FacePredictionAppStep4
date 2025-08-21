package com.faceprediction.form;

/**
 * FaceForm クラス
 *
 * 顔画像アップロード画面などから入力される情報を保持するフォームオブジェクト。
 * エンティティ (FaceImage) とは分離しており、
 * コントローラとView (HTMLフォーム) の間でデータ受け渡しを行う役割を持つ。
 *
 * フィールド:
 *   - horseName      : 馬の名前
 *   - trackCondition : 馬場状態
 */
public class FaceForm {

    /** 馬の名前（ユーザ入力） */
    private String horseName;

    /** 馬場状態（ユーザ入力: 良 / 重 / 不良 など） */
    private String trackCondition;

    // --- コンストラクタ ---
    public FaceForm() {
        // デフォルトコンストラクタ（フォーム初期表示時などに利用）
    }

    public FaceForm(String horseName, String trackCondition) {
        this.horseName = horseName;
        this.trackCondition = trackCondition;
    }

    // --- Getter / Setter ---
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
}
