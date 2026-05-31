"""
cleanup_bad_data.py — 空のrace_nameレコードを削除し、当日の全レース情報を表示

使い方:
  python cleanup_bad_data.py
"""
import os
import psycopg2
from datetime import date
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

conn = psycopg2.connect(
    host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', '5432'),
    dbname=os.getenv('DB_NAME', 'faceapp'), user=os.getenv('DB_USER', 'postgres'),
    password=os.getenv('DB_PASSWORD', 'postgrestest')
)
cur = conn.cursor()

# 1. 不正データを削除
cur.execute("DELETE FROM stats_prediction WHERE race_name='' OR race_name IS NULL")
n1 = cur.rowcount
cur.execute("DELETE FROM race_entry WHERE race_name='' OR race_name IS NULL")
n2 = cur.rowcount
conn.commit()
print(f"削除: stats_prediction {n1}件 / race_entry {n2}件\n")

# 2. 今日のレース一覧を表示
print("=" * 70)
print(f"  {date.today()} のレース一覧")
print("=" * 70)
cur.execute("""
    SELECT DISTINCT race_id, race_name
    FROM race_entry
    WHERE race_date = CURRENT_DATE
    ORDER BY race_id
""")
rows = cur.fetchall()
if not rows:
    print("  本日のレースなし")
else:
    print(f"  {'race_id':<14} {'レース名'}")
    print(f"  {'-' * 60}")
    for race_id, race_name in rows:
        print(f"  {race_id:<14} {race_name}")
print("=" * 70)

cur.close()
conn.close()
