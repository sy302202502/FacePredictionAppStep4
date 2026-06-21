"""dedup_stats.py — stats_prediction の重複行を除去する。
同一 (race_name, horse_id) が複数ある場合、顔面分析済みを優先して1行だけ残す。
使い方:
  python dedup_stats.py            # 今日〜明日のレースを対象
  python dedup_stats.py --all      # 全レースを対象
"""
import sys, os
import psycopg2
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST'), port=os.getenv('DB_PORT'),
        dbname=os.getenv('DB_NAME'), user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        connect_timeout=15, options='-c statement_timeout=60000')

all_mode = '--all' in sys.argv
conn = get_conn()
cur = conn.cursor()

if all_mode:
    target_names = None
    print("対象: 全レース")
else:
    today = date.today()
    cur.execute("""
        SELECT DISTINCT race_name FROM race_entry
        WHERE race_date BETWEEN %s AND %s
    """, (today, today + timedelta(days=1)))
    target_names = [r[0] for r in cur.fetchall()]
    print(f"対象: 今日〜明日の {len(target_names)}レース")

# 重複を検出して、各 (race_name, horse_id) で1行だけ残す。
# 残す優先順位: face_comment あり > id が小さい
where = "" if all_mode else "WHERE race_name = ANY(%s)"
params = () if all_mode else (target_names,)
cur.execute(f"""
    DELETE FROM stats_prediction sp
    USING (
        SELECT id,
               ROW_NUMBER() OVER (
                   PARTITION BY race_name, horse_id
                   ORDER BY (face_comment IS NOT NULL) DESC, id ASC
               ) AS rn
        FROM stats_prediction
        {where}
    ) dup
    WHERE sp.id = dup.id AND dup.rn > 1
""", params)
deleted = cur.rowcount
conn.commit()
cur.close()
conn.close()
print(f"\n重複削除: {deleted}行")
print("完了。各馬1行になりました。")
