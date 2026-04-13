"""
setup_db.py
競馬顔面予想アプリ用のDBテーブルを作成・マイグレーションするスクリプト
"""
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest')
    )

def setup():
    conn = get_conn()
    cur = conn.cursor()

    # -------------------------------------------------------
    # 重賞レース結果テーブル（レース種別カラムを追加）
    # -------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS grade_race_result (
            id SERIAL PRIMARY KEY,
            race_id VARCHAR(20) UNIQUE,
            race_name VARCHAR(200),
            race_date DATE,
            grade VARCHAR(10),
            venue VARCHAR(50),
            distance INTEGER,
            surface VARCHAR(10),          -- 芝 / ダート
            race_category VARCHAR(30),    -- sprint/mile/middle/long/dirt
            winner_horse_name VARCHAR(100),
            winner_horse_id VARCHAR(20),
            image_url VARCHAR(500),
            image_path VARCHAR(500),
            analyzed BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    # 既存テーブルへのカラム追加（既にあればスキップ）
    for col, definition in [
        ('distance',      'INTEGER'),
        ('surface',       'VARCHAR(10)'),
        ('race_category', 'VARCHAR(30)'),
    ]:
        cur.execute(f"""
            ALTER TABLE grade_race_result
            ADD COLUMN IF NOT EXISTS {col} {definition}
        """)

    # -------------------------------------------------------
    # 馬の顔特徴テーブル
    #   is_winner     : True=勝ち馬, False=負け馬(2〜5着)
    #   finish_rank   : 着順(1〜5)
    #   analysis_count: 分析回数（多数決用）
    #   race_category : レース種別
    #   数値特徴量 (eye_aspect_ratio など)
    # -------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS horse_face_feature (
            id SERIAL PRIMARY KEY,
            horse_name VARCHAR(100),
            horse_id VARCHAR(20),
            image_path VARCHAR(500),
            finish_rank INTEGER DEFAULT 1,
            race_category VARCHAR(30),

            -- ラベル特徴（多数決確定済み）
            nose_shape VARCHAR(100),
            eye_size VARCHAR(50),
            eye_shape VARCHAR(100),
            face_contour VARCHAR(100),
            forehead_width VARCHAR(50),
            nostril_size VARCHAR(50),
            jaw_line VARCHAR(50),
            overall_impression VARCHAR(200),

            -- 数値特徴量（0.0〜1.0 または実数）
            eye_aspect_ratio FLOAT,        -- 目の縦横比（細長さ）
            nose_width_ratio FLOAT,        -- 鼻幅/顔幅 比率
            face_aspect_ratio FLOAT,       -- 顔の縦横比
            jaw_strength_score FLOAT,      -- 顎の強さスコア
            overall_intensity FLOAT,       -- 全体的な迫力スコア

            -- 分析信頼度
            analysis_count INTEGER DEFAULT 1,   -- 分析した回数
            avg_confidence FLOAT DEFAULT 0.0,   -- 平均確信度

            raw_analysis TEXT,
            is_winner BOOLEAN DEFAULT FALSE,
            win_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    # 既存テーブルへのカラム追加
    for col, definition in [
        ('finish_rank',        'INTEGER DEFAULT 1'),
        ('race_category',      'VARCHAR(30)'),
        ('eye_aspect_ratio',   'FLOAT'),
        ('nose_width_ratio',   'FLOAT'),
        ('face_aspect_ratio',  'FLOAT'),
        ('jaw_strength_score', 'FLOAT'),
        ('overall_intensity',  'FLOAT'),
        ('analysis_count',     'INTEGER DEFAULT 1'),
        ('avg_confidence',     'FLOAT DEFAULT 0.0'),
    ]:
        cur.execute(f"""
            ALTER TABLE horse_face_feature
            ADD COLUMN IF NOT EXISTS {col} {definition}
        """)

    # -------------------------------------------------------
    # 予想結果テーブル（レース種別・差分スコア追加）
    # -------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prediction_result (
            id SERIAL PRIMARY KEY,
            target_race_name VARCHAR(200),
            target_race_date DATE,
            race_category VARCHAR(30),
            horse_name VARCHAR(100),
            horse_id VARCHAR(20),
            image_path VARCHAR(500),
            similarity_score FLOAT,       -- 勝ち馬プロファイルとの類似度
            diff_score FLOAT,             -- 差分スコア（勝ち馬 - 負け馬 の差を加味）
            final_score FLOAT,            -- 最終スコア（similarity + diff の合算）
            rank_position INTEGER,
            analysis_detail TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    for col, definition in [
        ('race_category', 'VARCHAR(30)'),
        ('diff_score',    'FLOAT'),
        ('final_score',   'FLOAT'),
    ]:
        cur.execute(f"""
            ALTER TABLE prediction_result
            ADD COLUMN IF NOT EXISTS {col} {definition}
        """)

    # -------------------------------------------------------
    # 予測精度トラッキングテーブル
    #   actual_rank     : レース後に記録する実際の着順
    #   hit             : TOP5に入った馬が実際に勝ったか(1着=True)
    #   top5_hit        : 勝ち馬が予想TOP5に含まれていたか
    # -------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prediction_accuracy (
            id SERIAL PRIMARY KEY,
            prediction_id INTEGER REFERENCES prediction_result(id),
            race_name VARCHAR(200),
            race_date DATE,
            race_category VARCHAR(30),
            horse_name VARCHAR(100),
            predicted_rank INTEGER,       -- 予想順位（1〜5）
            actual_rank INTEGER,          -- 実際の着順（レース後に記録）
            hit BOOLEAN,                  -- 予想1位が実際1着か
            top5_hit BOOLEAN,             -- 勝ち馬が予想TOP5に入っていたか
            final_score FLOAT,
            recorded_at TIMESTAMP DEFAULT NOW()
        )
    """)
    for col, definition in [
        ('prediction_id',  'INTEGER'),
        ('race_category',  'VARCHAR(30)'),
        ('top5_hit',       'BOOLEAN'),
        ('final_score',    'FLOAT'),
    ]:
        cur.execute(f"""
            ALTER TABLE prediction_accuracy
            ADD COLUMN IF NOT EXISTS {col} {definition}
        """)

    # -------------------------------------------------------
    # 出走馬エントリテーブル（自動取得した出走予定馬）
    # -------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_entry (
            id SERIAL PRIMARY KEY,
            race_id VARCHAR(20),
            race_name VARCHAR(200),
            race_date DATE,
            race_category VARCHAR(30),
            grade VARCHAR(10),
            venue VARCHAR(50),
            distance INTEGER,
            surface VARCHAR(10),
            horse_name VARCHAR(100),
            horse_id VARCHAR(20),
            post_position INTEGER,        -- 枠番
            horse_number INTEGER,         -- 馬番
            jockey_name VARCHAR(100),
            image_path VARCHAR(500),
            fetched_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # -------------------------------------------------------
    # レース特化型予想 - パターンサマリテーブル
    #   race_name        : 対象レース名（例：日本ダービー）
    #   top5_pattern_json: {feature: {value: freq%}} の JSON
    #   top5_comment     : 5着内馬の傾向コメント
    #   bottom_comment   : 6着以下の傾向コメント
    #   confidence_level : データ量に基づく信頼度 1〜5
    # -------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_specific_prediction (
            id SERIAL PRIMARY KEY,
            race_name VARCHAR(200) UNIQUE,
            total_years INTEGER DEFAULT 0,
            total_horses INTEGER DEFAULT 0,
            top5_horses INTEGER DEFAULT 0,
            bottom_horses INTEGER DEFAULT 0,
            top5_pattern_json TEXT,
            bottom_pattern_json TEXT,
            top5_comment TEXT,
            bottom_comment TEXT,
            diff_comment TEXT,
            supplemental_count INTEGER DEFAULT 0,
            confidence_level INTEGER DEFAULT 3,
            analyzed_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # -------------------------------------------------------
    # レース特化型予想 - 出走馬別スコアテーブル
    #   data_source: image / pedigree / text_only
    # -------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_specific_result (
            id SERIAL PRIMARY KEY,
            race_name VARCHAR(200),
            horse_name VARCHAR(100),
            horse_id VARCHAR(20),
            image_path VARCHAR(500),
            rank_position INTEGER,
            score FLOAT,
            confidence_level INTEGER DEFAULT 3,
            comment TEXT,
            feature_json TEXT,
            data_source VARCHAR(20) DEFAULT 'image',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # -------------------------------------------------------
    # 顔面傾向分析予想（新システム）の的中記録テーブル
    # -------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_specific_accuracy (
            id SERIAL PRIMARY KEY,
            race_name VARCHAR(200),
            horse_name VARCHAR(100),
            predicted_rank INTEGER,
            actual_rank INTEGER,
            hit BOOLEAN DEFAULT FALSE,
            top5_hit BOOLEAN DEFAULT FALSE,
            score FLOAT,
            data_source VARCHAR(20) DEFAULT 'image',
            recorded_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # -------------------------------------------------------
    # オッズキャッシュテーブル（当日オッズ取得用）
    # -------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_odds (
            id SERIAL PRIMARY KEY,
            race_id VARCHAR(20),
            race_name VARCHAR(200),
            horse_name VARCHAR(100),
            horse_id VARCHAR(20),
            win_odds FLOAT,
            popularity INTEGER,
            fetched_at TIMESTAMP DEFAULT NOW()
        )
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("DBテーブルの作成・マイグレーションが完了しました。")

if __name__ == '__main__':
    setup()
