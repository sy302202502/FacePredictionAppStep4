-- migrate_v2.sql
-- 既存DBへのマイグレーション（schema.sqlの修正内容を既存環境に適用）
-- 実行: psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f deploy/migrate_v2.sql

-- 1. 重複カラム top5hit を削除（top5_hit を正式カラムとして統一）
ALTER TABLE prediction_accuracy DROP COLUMN IF EXISTS top5hit;
ALTER TABLE race_specific_accuracy DROP COLUMN IF EXISTS top5hit;

-- 2. race_specific_result に UNIQUE 制約追加（重複レコード防止）
DO $$ BEGIN
    ALTER TABLE race_specific_result
        ADD CONSTRAINT race_specific_result_race_horse_key UNIQUE (race_name, horse_name);
EXCEPTION WHEN OTHERS THEN NULL; END $$;

-- 3. race_specific_prediction に UNIQUE 制約追加
DO $$ BEGIN
    ALTER TABLE race_specific_prediction
        ADD CONSTRAINT race_specific_prediction_race_name_key UNIQUE (race_name);
EXCEPTION WHEN OTHERS THEN NULL; END $$;

-- 4. race_entry に sex カラムがなければ追加（entry_fetcher.py依存を解消）
ALTER TABLE race_entry ADD COLUMN IF NOT EXISTS sex VARCHAR(2);
