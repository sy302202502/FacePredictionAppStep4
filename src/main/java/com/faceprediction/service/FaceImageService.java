package com.faceprediction.service;

import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import com.faceprediction.entity.FaceImage;
import com.faceprediction.repository.FaceImageRepository;

/**
 * FaceImageService クラス
 *
 * FaceImageRepository を利用して、顔画像(FaceImageエンティティ)に関する
 * ビジネスロジックやデータ操作を提供するサービス層。
 *
 * コントローラ層から呼び出されることで、
 * データベースへの直接アクセスを隠蔽し、役割分担を明確にする。
 */
@Service  // Springにより自動的にDIコンテナへ登録される（サービスクラスとして認識される）
public class FaceImageService {

    private final FaceImageRepository faceImageRepository;

    /**
     * コンストラクタインジェクションによるリポジトリの注入
     * @param faceImageRepository 顔画像用リポジトリ
     */
    @Autowired
    public FaceImageService(FaceImageRepository faceImageRepository) {
        this.faceImageRepository = faceImageRepository;
    }

    /**
     * 顔画像を全件取得
     * @return データベースに保存されている全FaceImageリスト
     */
    public List<FaceImage> findAll() {
        return faceImageRepository.findAll();
    }

    /**
     * 顔画像を保存（新規登録または更新）
     * @param faceImage 保存する顔画像エンティティ
     * @return 保存後のFaceImage（DBに反映されたもの）
     */
    public FaceImage save(FaceImage faceImage) {
        return faceImageRepository.save(faceImage);
    }

    /**
     * 馬名で顔画像を検索
     * @param horseName 馬名
     * @return 指定された馬名に一致する顔画像リスト
     */
    public List<FaceImage> findByHorseName(String horseName) {
        return faceImageRepository.findByHorseName(horseName);
    }

    /**
     * 馬場状態で顔画像を検索
     * @param trackCondition 馬場状態（例: 良・稍重・重・不良）
     * @return 指定された馬場状態に一致する顔画像リスト
     */
    public List<FaceImage> findByTrackCondition(String trackCondition) {
        return faceImageRepository.findByTrackCondition(trackCondition);
    }

    /**
     * 馬名と馬場状態の両方で顔画像を検索
     * @param horseName 馬名
     * @param trackCondition 馬場状態
     * @return 両方の条件に一致する顔画像リスト
     */
    public List<FaceImage> findByHorseNameAndTrackCondition(String horseName, String trackCondition) {
        return faceImageRepository.findByHorseNameAndTrackCondition(horseName, trackCondition);
    }
}
