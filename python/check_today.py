"""
check_today.py — 予想・顔面分析の完了状況を確認する

使い方:
  python check_today.py            # 全レース（顔面分析が新しい順）
  python check_today.py 2026-05-24 # face_analyzed_at が指定日のレースのみ
"""
import sys, os
import psycopg2
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

target = sys.argv[1] if len(sys.argv) > 1 else None

conn = psycopg2.connect(
    host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', '5432'),
    dbname=os.getenv('DB_NAME', 'faceapp'), user=os.getenv('DB_USER', 'postgres'),
    password=os.getenv('DB_PASSWORD', 'postgrestest')
)
cur = conn.cursor()

base = """
    SELECT race_name,
           COUNT(*)                       AS horses,
           COUNT(face_comment)            AS face_done,
           COUNT(CASE WHEN face_score IS NOT NULL AND face_score <> 50.0 THEN 1 END) AS valid_score,
           MAX(face_analyzed_at)          AS last_analyzed
    FROM stats_prediction
"""
if target:
    base += " WHERE face_analyzed_at::date = %s GROUP BY race_name ORDER BY race_name"
    cur.execute(base, (target,))
    title = f"face_analyzed_at = {target} のレース"
else:
    base += " GROUP BY race_name ORDER BY MAX(face_analyzed_at) DESC NULLS LAST LIMIT 30"
    cur.execute(base)
    title = "全レース（顔面分析が新しい順 上位30件）"

rows = cur.fetchall()

print(f"\n{'='*78}")
print(f"  {title}")
print(f"{'='*78}")
if not rows:
    print("  該当レースなし")
else:
    print(f"  {'状態':<3} {'レース名':<22} {'出走':>4} {'顔面':>5} {'有効':>5}  分析日時")
    print(f"  {'-'*72}")
    for race_name, horses, face_done, valid_score, last_analyzed in rows:
        ok = face_done == horses and valid_score > 0
        status = "OK " if ok else "NG "
        dt = last_analyzed.strftime('%m-%d %H:%M') if last_analyzed else '未分析'
        print(f"  {status} {race_name:<22} {horses:>4} {face_done:>5} {valid_score:>5}  {dt}")
print(f"{'='*78}\n")

cur.close()
conn.close()
