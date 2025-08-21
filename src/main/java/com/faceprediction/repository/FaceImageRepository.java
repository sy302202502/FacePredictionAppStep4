package com.faceprediction.repository;

import java.util.List;

import org.springframework.data.jpa.repository.JpaRepository;

import com.faceprediction.entity.FaceImage;

/**
 * FaceImageRepository インターフェース
 *
 * FaceImage エンティティに対応するデータベース操作を提供するリポジトリ。
 * Spring Data JPA の JpaRepository を継承することで、
 * CRUD（作成・取得・更新・削除）操作が自動的に利用可能になる。
 *
 * さらに、メソッド名に基づいてクエリを自動生成する
 * 「クエリメソッド」を定義している。
 */
public interface FaceImageRepository extends JpaRepository<FaceImage, Long> {

    /**
     * 馬名で検索するクエリメソッド
     * SQL例: SELECT * FROM face_images WHERE horse_name = ?
     *
     * @param horseName 検索対象の馬名
     * @return 一致するFaceImageのリスト
     */
    List<FaceImage> findByHorseName(String horseName);

    /**
     * 馬場状態で検索するクエリメソッド
     * SQL例: SELECT * FROM face_images WHERE track_condition = ?
     *
     * @param trackCondition 検索対象の馬場状態
     * @return 一致するFaceImageのリスト
     */
    List<FaceImage> findByTrackCondition(String trackCondition);

    /**
     * 馬名と馬場状態を両方指定して検索するクエリメソッド
     * SQL例:
     *   SELECT * FROM face_images
     *   WHERE horse_name = ? AND track_condition = ?
     *
     * @param horseName 馬名
     * @param trackCondition 馬場状態
     * @return 条件に一致するFaceImageのリスト
     */
    List<FaceImage> findByHorseNameAndTrackCondition(String horseName, String trackCondition);
}
