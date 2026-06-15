"""diag_race.py — 指定レース名/race_idの予想完了状況を詳細診断する
使い方: python diag_race.py 宝塚記念   または  python diag_race.py 202609030411
"""
import sys, os
import psycopg2
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

q = sys.argv[1] if len(sys.argv) > 1 else '宝塚記念'
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'), port=os.getenv('DB_PORT'),
    dbname=os.getenv('DB_NAME'), user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'), connect_timeout=20)
cur = conn.cursor()

if q.isdigit():
    cur.execute("SELECT DISTINCT race_name FROM race_entry WHERE race_id=%s", (q,))
    row = cur.fetchone()
    name = row[0] if row else None
    print(f"race_id={q} -> race_name={name}")
else:
    name = q

print("\n=== race_entry ===")
cur.execute("""SELECT race_id, race_date, COUNT(*) AS heads,
               COUNT(horse_number) AS with_num, COUNT(image_path) AS with_img
               FROM race_entry WHERE race_name=%s GROUP BY race_id, race_date""", (name,))
for r in cur.fetchall():
    print(f"  race_id={r[0]} date={r[1]} 出走{r[2]}頭 馬番{r[3]} 画像{r[4]}")

print("\n=== stats_prediction（予想結果テーブル）===")
cur.execute("""SELECT COUNT(*) AS rows,
               COUNT(score) AS with_score,
               COUNT(face_comment) AS with_face_comment,
               COUNT(face_score) AS with_face_score,
               COUNT(image_path) AS with_img,
               MAX(face_analyzed_at) AS last_face,
               MAX(created_at) AS last_created
               FROM stats_prediction WHERE race_name=%s""", (name,))
r = cur.fetchone()
print(f"  行数={r[0]} 統計スコア={r[1]} 顔面コメント={r[2]} 顔面スコア={r[3]} 画像={r[4]}")
print(f"  最終顔面分析={r[5]} 最終作成={r[6]}")

print("\n=== /predict-v2 が実際に表示する行（INNER JOIN後）===")
cur.execute("""
    SELECT sp.rank_position, sp.horse_name, sp.face_score, sp.score, re.horse_number
    FROM stats_prediction sp
    INNER JOIN race_entry re ON re.race_name=sp.race_name AND re.horse_name=sp.horse_name
      AND re.race_id = (SELECT race_id FROM race_entry WHERE race_name=sp.race_name
                        ORDER BY race_date DESC, race_id DESC LIMIT 1)
    WHERE sp.race_name=%s ORDER BY sp.rank_position""", (name,))
rows = cur.fetchall()
print(f"  JOIN後の表示行数: {len(rows)}")
for r in rows[:5]:
    print(f"    {r[0]}位 {r[1]} 顔面={r[2]} 統計={r[3]} 馬番={r[4]}")

conn.close()
