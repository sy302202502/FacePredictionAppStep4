"""
weight_learner.py
的中データから「勝ち馬顔特徴の重み」を自動学習して race_specific_prediction を更新

【仕組み】
  race_specific_accuracy（実際の結果）と race_specific_result（予想）を照合
  ↓
  的中した予想 → 使われた特徴の重みを UP
  外れた予想   → 使われた特徴の重みを DOWN
  ↓
  次回の race_specific_analyzer.py がこの重みを参照してスコアリング

使い方:
  python weight_learner.py           # 全レースのデータで学習
  python weight_learner.py --report  # 現在の重みを表示
"""
import sys
import os
import json
import psycopg2
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)

FEATURE_KEYS = [
    'nose_shape', 'eye_size', 'eye_shape', 'face_contour',
    'forehead_width', 'nostril_size', 'jaw_line', 'overall_impression',
    'eye_aspect_ratio', 'nose_width_ratio', 'face_aspect_ratio',
    'jaw_strength_score', 'overall_intensity'
]

FEATURE_LABELS_JP = {
    'nose_shape':         '鼻の形',
    'eye_size':           '目のサイズ',
    'eye_shape':          '目の形',
    'face_contour':       '顔の輪郭',
    'forehead_width':     '額の広さ',
    'nostril_size':       '鼻孔の大きさ',
    'jaw_line':           '顎のライン',
    'overall_impression': '全体的な印象',
    'eye_aspect_ratio':   '目の縦横比',
    'nose_width_ratio':   '鼻幅比率',
    'face_aspect_ratio':  '顔の縦横比',
    'jaw_strength_score': '顎の強さ',
    'overall_intensity':  '迫力スコア',
}

# デフォルト重み（全て1.0 = 均等）
DEFAULT_WEIGHTS = {k: 1.0 for k in FEATURE_KEYS}

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest')
    )

def ensure_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS feature_weights (
            id SERIAL PRIMARY KEY,
            feature_key VARCHAR(100) UNIQUE,
            weight FLOAT DEFAULT 1.0,
            hit_count INTEGER DEFAULT 0,
            miss_count INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    # 初期データを挿入（なければ）
    for key in FEATURE_KEYS:
        cur.execute("""
            INSERT INTO feature_weights (feature_key, weight)
            VALUES (%s, 1.0)
            ON CONFLICT (feature_key) DO NOTHING
        """, (key,))
    conn.commit()
    cur.close()

def load_weights(conn):
    """DBから現在の重みを取得"""
    cur = conn.cursor()
    cur.execute("SELECT feature_key, weight FROM feature_weights")
    rows = cur.fetchall()
    cur.close()
    weights = dict(DEFAULT_WEIGHTS)  # デフォルトで初期化
    for key, w in rows:
        weights[key] = w
    return weights

def save_weights(conn, weights, hit_counts, miss_counts):
    cur = conn.cursor()
    for key, w in weights.items():
        cur.execute("""
            UPDATE feature_weights
            SET weight = %s,
                hit_count  = hit_count  + %s,
                miss_count = miss_count + %s,
                updated_at = NOW()
            WHERE feature_key = %s
        """, (w, hit_counts.get(key, 0), miss_counts.get(key, 0), key))
    conn.commit()
    cur.close()

def learn(conn):
    """
    的中記録から特徴重みを更新する

    アルゴリズム:
      1. 的中レース(hit=True)のTOP予想馬の feature_json を取得
      2. 外れレース(hit=False)のTOP予想馬の feature_json を取得
      3. 的中馬の特徴ごとに出現回数を集計（hit_counts）
      4. 外れ馬の特徴ごとに出現回数を集計（miss_counts）
      5. 重み = 現在の重み × (1 + 0.05 × (hit_rate - 0.5))
         → 的中率50%以上の特徴は少し重みUP、以下は少しDOWN
         → 変動幅を±20%に制限して過学習を防ぐ
    """
    cur = conn.cursor()

    # 的中レース（hit=True）のTOP予想馬の特徴を取得
    cur.execute("""
        SELECT r.feature_json
        FROM race_specific_accuracy a
        JOIN race_specific_result r ON r.race_name = a.race_name
                                   AND r.horse_name = a.horse_name
        WHERE a.hit = TRUE AND a.predicted_rank = 1
          AND r.feature_json IS NOT NULL AND r.feature_json != '{}'
    """)
    hit_features = [row[0] for row in cur.fetchall()]

    # 外れレース（hit=False）のTOP予想馬の特徴を取得
    cur.execute("""
        SELECT r.feature_json
        FROM race_specific_accuracy a
        JOIN race_specific_result r ON r.race_name = a.race_name
                                   AND r.horse_name = a.horse_name
        WHERE a.hit = FALSE AND a.predicted_rank = 1
          AND r.feature_json IS NOT NULL AND r.feature_json != '{}'
    """)
    miss_features = [row[0] for row in cur.fetchall()]
    cur.close()

    total_hit  = len(hit_features)
    total_miss = len(miss_features)

    if total_hit + total_miss < 5:
        print(f"  学習データ不足（的中{total_hit}件、外れ{total_miss}件）")
        print("  最低5件の記録が必要です。「的中記録を自動取得」を実行してください。")
        return None, None, None

    print(f"  学習データ: 的中{total_hit}件 / 外れ{total_miss}件")

    # ラベル特徴の出現回数を集計
    label_keys = [k for k in FEATURE_KEYS if not k.endswith('_ratio') and not k.endswith('_score') and k != 'overall_intensity']
    hit_value_counts  = defaultdict(lambda: defaultdict(int))
    miss_value_counts = defaultdict(lambda: defaultdict(int))

    for fj in hit_features:
        try:
            f = json.loads(fj) if isinstance(fj, str) else fj
            for k in label_keys:
                if f.get(k):
                    hit_value_counts[k][f[k]] += 1
        except Exception:
            pass

    for fj in miss_features:
        try:
            f = json.loads(fj) if isinstance(fj, str) else fj
            for k in label_keys:
                if f.get(k):
                    miss_value_counts[k][f[k]] += 1
        except Exception:
            pass

    # 特徴ごとの「的中率」を計算して重みを更新
    current_weights = load_weights(conn)
    new_weights     = dict(current_weights)
    hit_delta       = defaultdict(int)
    miss_delta      = defaultdict(int)

    LEARNING_RATE = 0.05  # 1回の学習での最大変動率5%
    MAX_WEIGHT    = 2.0   # 重みの上限
    MIN_WEIGHT    = 0.3   # 重みの下限

    for key in label_keys:
        hit_total  = sum(hit_value_counts[key].values())
        miss_total = sum(miss_value_counts[key].values())
        total      = hit_total + miss_total
        if total == 0:
            continue

        hit_rate = hit_total / total  # この特徴が的中馬に出てくる割合
        # hit_rate > 0.5 → 的中に貢献する特徴 → 重みUP
        adjustment = LEARNING_RATE * (hit_rate - 0.5) * 2  # -0.05 〜 +0.05
        new_w = current_weights.get(key, 1.0) * (1 + adjustment)
        new_w = max(MIN_WEIGHT, min(MAX_WEIGHT, new_w))
        new_weights[key] = round(new_w, 4)

        hit_delta[key]  = hit_total
        miss_delta[key] = miss_total

    # 数値特徴も同様に（符号で方向を判断）
    numeric_keys = ['eye_aspect_ratio', 'nose_width_ratio', 'face_aspect_ratio',
                    'jaw_strength_score', 'overall_intensity']

    def get_numerics(features_list, key):
        vals = []
        for fj in features_list:
            try:
                f = json.loads(fj) if isinstance(fj, str) else fj
                v = f.get(key)
                if v is not None:
                    vals.append(float(v))
            except Exception:
                pass
        return vals

    for key in numeric_keys:
        hit_vals  = get_numerics(hit_features, key)
        miss_vals = get_numerics(miss_features, key)
        if len(hit_vals) < 2 or len(miss_vals) < 2:
            continue
        hit_mean  = sum(hit_vals)  / len(hit_vals)
        miss_mean = sum(miss_vals) / len(miss_vals)
        # 的中馬と外れ馬で値が大きく離れていれば重みUP
        diff_ratio = abs(hit_mean - miss_mean) / (abs(hit_mean) + 0.001)
        bonus = LEARNING_RATE * min(1.0, diff_ratio * 2)
        new_w = current_weights.get(key, 1.0) * (1 + bonus)
        new_w = max(MIN_WEIGHT, min(MAX_WEIGHT, new_w))
        new_weights[key] = round(new_w, 4)

    return new_weights, hit_delta, miss_delta

def show_report(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT feature_key, weight, hit_count, miss_count
        FROM feature_weights
        ORDER BY weight DESC
    """)
    rows = cur.fetchall()
    cur.close()

    print("\n" + "="*60)
    print("  特徴重みレポート（重み順）")
    print("="*60)
    print(f"  {'特徴名':22} {'重み':6}  {'的中':5}  {'外れ':5}  {'的中率':8}")
    print("-"*60)
    for key, weight, hits, misses in rows:
        label = FEATURE_LABELS_JP.get(key, key)
        total = (hits or 0) + (misses or 0)
        rate  = f"{hits/total*100:.0f}%" if total > 0 else "---"
        bar   = "█" * int((weight / 2.0) * 10) + "░" * (10 - int((weight / 2.0) * 10))
        print(f"  {label:22} {weight:6.3f}  {hits or 0:5}  {misses or 0:5}  {rate:8}  {bar}")
    print("="*60)

def main():
    report = '--report' in sys.argv
    conn   = get_conn()
    ensure_table(conn)

    if report:
        show_report(conn)
        conn.close()
        return

    print("=== 特徴重み 自動学習 ===\n")
    new_weights, hit_delta, miss_delta = learn(conn)

    if new_weights is None:
        conn.close()
        return

    save_weights(conn, new_weights, hit_delta or {}, miss_delta or {})

    print("\n  更新後の重み（上位5件）:")
    sorted_weights = sorted(new_weights.items(), key=lambda x: x[1], reverse=True)
    for key, w in sorted_weights[:5]:
        label = FEATURE_LABELS_JP.get(key, key)
        direction = "↑" if w > 1.0 else ("↓" if w < 1.0 else "→")
        print(f"    {direction} {label}: {w:.3f}")

    conn.close()
    print("\n=== 完了 ===")
    print("次回の race_specific_analyzer.py 実行時に自動で新しい重みが使われます。")

if __name__ == '__main__':
    main()
