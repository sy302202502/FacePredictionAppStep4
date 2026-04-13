"""
accuracy_tracker.py
レース後に実際の結果を記録して予測精度を集計するスクリプト

使い方:
  # レース結果を記録（レース名、実際1着の馬名を指定）
  python accuracy_tracker.py record "日本ダービー" "ドウデュース"

  # 精度レポートを表示
  python accuracy_tracker.py report

  # レース種別ごとの精度比較
  python accuracy_tracker.py report --by-category
"""
import sys
import os
import psycopg2
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

CATEGORY_LABEL = {
    'sprint': '短距離（〜1400m）',
    'mile':   'マイル（1600〜1800m）',
    'middle': '中距離（2000〜2200m）',
    'long':   '長距離（2400m〜）',
    'dirt':   'ダート',
    'all':    '全カテゴリ',
}

def record_result(race_name, actual_winner_name):
    """
    レース後に実際の勝ち馬を記録し、予想との照合を行う
    """
    conn = get_conn()
    cur = conn.cursor()

    # 該当レースの予想結果を取得
    cur.execute("""
        SELECT id, horse_name, rank_position, final_score, race_category, target_race_date
        FROM prediction_result
        WHERE target_race_name = %s
        ORDER BY rank_position
    """, (race_name,))
    predictions = cur.fetchall()

    if not predictions:
        print(f"[エラー] '{race_name}'の予想データが見つかりません")
        cur.close()
        conn.close()
        return

    race_date = predictions[0][5]
    race_category = predictions[0][4]

    # TOP5に勝ち馬が含まれているか
    top5_names = [p[1] for p in predictions[:5]]
    top5_hit = actual_winner_name in top5_names

    # 予想1位が勝ったか
    predicted_winner = predictions[0][1] if predictions else None
    hit_1st = (predicted_winner == actual_winner_name)

    print(f"\n=== {race_name} 結果記録 ===")
    print(f"  実際の勝ち馬: {actual_winner_name}")
    print(f"  予想1位:      {predicted_winner}")
    print(f"  1位的中:      {'✓' if hit_1st else '✗'}")
    print(f"  TOP5的中:     {'✓' if top5_hit else '✗'}")

    # 各馬の実際の着順を取得（DBにあれば）
    for pred_id, horse_name, pred_rank, final_score, cat, r_date in predictions:
        actual_rank = 1 if horse_name == actual_winner_name else None

        # 既存レコードを確認
        cur.execute("""
            SELECT id FROM prediction_accuracy
            WHERE prediction_id = %s
        """, (pred_id,))
        existing = cur.fetchone()

        if existing:
            cur.execute("""
                UPDATE prediction_accuracy
                SET actual_rank = %s, hit = %s, top5_hit = %s, recorded_at = NOW()
                WHERE prediction_id = %s
            """, (actual_rank, hit_1st and pred_rank == 1, top5_hit, pred_id))
        else:
            cur.execute("""
                INSERT INTO prediction_accuracy
                    (prediction_id, race_name, race_date, race_category,
                     horse_name, predicted_rank, actual_rank,
                     hit, top5_hit, final_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                pred_id, race_name, race_date, cat,
                horse_name, pred_rank, actual_rank,
                hit_1st and pred_rank == 1, top5_hit, final_score
            ))

    conn.commit()
    cur.close()
    conn.close()
    print(f"\n記録完了。")

def show_report(by_category=False):
    """精度レポートを表示"""
    conn = get_conn()
    cur = conn.cursor()

    # 全体統計
    cur.execute("""
        SELECT
            COUNT(DISTINCT race_name) AS total_races,
            SUM(CASE WHEN hit = TRUE AND predicted_rank = 1 THEN 1 ELSE 0 END) AS win_hits,
            SUM(CASE WHEN top5_hit = TRUE THEN 1 ELSE 0 END) AS top5_hits,
            COUNT(DISTINCT CASE WHEN top5_hit IS NOT NULL THEN race_name END) AS recorded_races
        FROM prediction_accuracy
        WHERE predicted_rank = 1
    """)
    row = cur.fetchone()
    total, win_hits, top5_hits, recorded = row if row else (0, 0, 0, 0)

    print("\n" + "="*55)
    print("  予測精度レポート")
    print("="*55)
    print(f"  予想済みレース総数  : {total}レース")
    print(f"  結果記録済み        : {recorded}レース")
    if recorded and recorded > 0:
        print(f"  1位的中率           : {win_hits}/{recorded} = {win_hits/recorded*100:.1f}%")
        print(f"  TOP5的中率          : {top5_hits}/{recorded} = {top5_hits/recorded*100:.1f}%")

    if by_category:
        print("\n  --- レース種別ごとの的中率 ---")
        cur.execute("""
            SELECT
                race_category,
                COUNT(DISTINCT race_name) AS races,
                SUM(CASE WHEN hit = TRUE AND predicted_rank = 1 THEN 1 ELSE 0 END) AS win_hits,
                SUM(CASE WHEN top5_hit = TRUE THEN 1 ELSE 0 END) AS top5_hits
            FROM prediction_accuracy
            WHERE predicted_rank = 1 AND top5_hit IS NOT NULL
            GROUP BY race_category
            ORDER BY race_category
        """)
        rows = cur.fetchall()
        for cat, races, wh, th in rows:
            label = CATEGORY_LABEL.get(cat, cat)
            win_pct = f"{wh/races*100:.1f}%" if races > 0 else "---"
            top5_pct = f"{th/races*100:.1f}%" if races > 0 else "---"
            print(f"  {label:20s}: {races}R  1位:{win_pct:6s}  TOP5:{top5_pct}")

    print("\n  --- 直近10レースの予想精度 ---")
    cur.execute("""
        SELECT DISTINCT ON (race_name)
            race_name, race_date, race_category,
            top5_hit,
            (SELECT horse_name FROM prediction_accuracy pa2
             WHERE pa2.race_name = pa.race_name AND pa2.hit = TRUE LIMIT 1) AS hit_horse
        FROM prediction_accuracy pa
        WHERE top5_hit IS NOT NULL
        ORDER BY race_name, race_date DESC
        LIMIT 10
    """)
    recent = cur.fetchall()
    for rname, rdate, cat, t5, hh in recent:
        mark = "✓" if t5 else "✗"
        label = CATEGORY_LABEL.get(cat, cat or "不明")
        print(f"  {mark} {str(rdate)} {rname[:20]:20s} [{label[:6]}]")

    print("="*55)
    cur.close()
    conn.close()

def main():
    args = sys.argv[1:]
    if not args:
        show_report(by_category=True)
        return

    cmd = args[0]
    if cmd == 'record':
        if len(args) < 3:
            print("使い方: python accuracy_tracker.py record \"レース名\" \"実際の勝ち馬名\"")
            sys.exit(1)
        record_result(args[1], args[2])
    elif cmd == 'report':
        by_cat = '--by-category' in args
        show_report(by_category=by_cat)
    else:
        print(f"不明なコマンド: {cmd}")
        print("使い方: record / report [--by-category]")

if __name__ == '__main__':
    main()
