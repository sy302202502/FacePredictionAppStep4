"""
check_today.py — 当日の予想・顔面分析の完了状況を確認する

使い方:
  python check_today.py            # 今日の分
  python check_today.py 2026-05-24 # 指定日
"""
import sys, os
import psycopg2
from datetime import date
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

target = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()

conn = psycopg2.connect(
    host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', '5432'),
    dbname=os.getenv('DB_NAME', 'faceapp'), user=os.getenv('DB_USER', 'postgres'),
    password=os.getenv('DB_PASSWORD', 'postgrestest')
)
cur = conn.cursor()
cur.execute("""
    SELECT race_name,
           COUNT(*)                       AS horses,
           COUNT(face_comment)            AS face_done,
           COUNT(CASE WHEN face_score IS NOT NULL AND face_score <> 50.0 THEN 1 END) AS valid_score
    FROM stats_prediction
    WHERE created_at::date = %s
    GROUP BY race_name
    ORDER BY race_name
""", (target,))
rows = cur.fetchall()

print(f"\n{'='*70}")
print(f"  {target} の予想完了状況")
print(f"{'='*70}")
if not rows:
    print("  該当レースなし")
else:
    print(f"  {'レース名':<24} {'出走':>4} {'顔面分析':>8} {'有効スコア':>10}")
    print(f"  {'-'*60}")
    for race_name, horses, face_done, valid_score in rows:
        status = "✅" if face_done == horses and valid_score > 0 else "⚠️"
        print(f"  {status} {race_name:<22} {horses:>4} {face_done:>8} {valid_score:>10}")
print(f"{'='*70}\n")

cur.close()
conn.close()
