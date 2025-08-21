package com.faceprediction.service;

import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import com.faceprediction.entity.Race;
import com.faceprediction.repository.RaceRepository;

/**
 * RaceService クラス
 *
 * Race エンティティ（レース情報）に関するビジネスロジックや
 * データベース操作を提供するサービス層。
 *
 * コントローラから呼び出されることで、リポジトリを直接使うことを避け、
 * 責務を分離する役割を担う。
 */
@Service  // Spring によってサービス層の Bean として管理される
public class RaceService {

    private final RaceRepository raceRepository;

    /**
     * コンストラクタインジェクションによりリポジトリを注入
     * @param raceRepository レース情報にアクセスするリポジトリ
     */
    @Autowired
    public RaceService(RaceRepository raceRepository) {
        this.raceRepository = raceRepository;
    }

    /**
     * レース情報を全件取得
     * @return データベースに保存されている全 Race エンティティのリスト
     */
    public List<Race> findAll() {
        return raceRepository.findAll();
    }

    /**
     * レース情報を保存（新規登録または更新）
     * @param race 保存対象のレースエンティティ
     * @return 保存後の Race エンティティ（DBに反映されたもの）
     */
    public Race save(Race race) {
        return raceRepository.save(race);
    }
}
