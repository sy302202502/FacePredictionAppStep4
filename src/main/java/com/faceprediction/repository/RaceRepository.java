package com.faceprediction.repository;

import org.springframework.data.jpa.repository.JpaRepository;

import com.faceprediction.entity.Race;

/**
 * RaceRepository インターフェース
 *
 * Race エンティティに対応するデータベース操作を提供するリポジトリ。
 * JpaRepository を継承することで以下のような基本的なCRUD処理が自動的に利用できる。
 *
 * - save(entity)     : レコードの新規登録や更新
 * - findById(id)     : 主キーによる検索
 * - findAll()        : 全件検索
 * - deleteById(id)   : 主キーによる削除
 *
 * このように、SQLを自分で書かなくても標準的な操作が可能になる。
 *
 * さらに必要に応じて「クエリメソッド」を追加定義することもできる。
 * 例: List<Race> findByLocation(String location);
 */
public interface RaceRepository extends JpaRepository<Race, Long> {
}
