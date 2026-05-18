-- パフォーマンス改善インデックス
-- 実行: psql -U postgres -d faceapp -f create_indexes.sql

-- stats_prediction: race_name GROUP BY + created_at ORDER BY
CREATE INDEX IF NOT EXISTS idx_stats_prediction_race_created
    ON stats_prediction(race_name, created_at DESC);

-- race_entry: race_name JOIN + race_date ORDER BY
CREATE INDEX IF NOT EXISTS idx_race_entry_race_name
    ON race_entry(race_name);
CREATE INDEX IF NOT EXISTS idx_race_entry_race_date
    ON race_entry(race_date);

-- race_specific_result: race_name (NOT EXISTS サブクエリ, JOIN)
CREATE INDEX IF NOT EXISTS idx_race_specific_result_race_name
    ON race_specific_result(race_name);
CREATE INDEX IF NOT EXISTS idx_race_specific_result_created_at
    ON race_specific_result(created_at DESC);

-- race_specific_accuracy: race_name (NOT EXISTS サブクエリ)
CREATE INDEX IF NOT EXISTS idx_race_specific_accuracy_race_name
    ON race_specific_accuracy(race_name);

-- prediction_accuracy: predictedRank + top5Hit (findRecordedResults, findCategoryStats)
CREATE INDEX IF NOT EXISTS idx_prediction_accuracy_rank_hit
    ON prediction_accuracy(predicted_rank, top5_hit, race_date DESC);

-- horse_face_feature: is_winner + nose_shape (findAllWinnersWithFeatures)
CREATE INDEX IF NOT EXISTS idx_horse_face_feature_winner_shape
    ON horse_face_feature(is_winner, nose_shape);
