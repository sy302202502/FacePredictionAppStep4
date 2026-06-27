"""status_all.py — 今日〜N日先の全レースの予想完了状況を一覧表示する。
出走頭数・統計予想・顔面分析・文字化けの有無を一目で確認できる。
使い方:
  python status_all.py            # 今日〜明日
  python status_all.py --days 14  # 今日から14日先まで
"""
import sys, os
import psycopg2
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)
from constants import is_garbled

days = 1
if '--days' in sys.argv:
    days = int(sys.argv[sys.argv.index('--days') + 1])

conn = psycopg2.connect(
    host=os.getenv('DB_HOST'), port=os.getenv('DB_PORT'),
    dbname=os.getenv('DB_NAME'), user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    connect_timeout=15, options='-c statement_timeout=60000')
cur = conn.cursor()
today = date.today()
cur.execute("""
    SELECT DISTINCT race_id, race_name, race_date
    FROM race_entry WHERE race_date BETWEEN %s AND %s
    ORDER BY race_date, race_id
""", (today, today + timedelta(days=days)))
races = cur.fetchall()

print(f"\n{'='*78}")
print(f"  予想状況 {today} 〜 {today + timedelta(days=days)}  ({len(races)}レース)")
print(f"{'='*78}")
print(f"  状態 race_id        日付       出走 統計 顔面 化け  レース名")
print(f"  {'-'*74}")

ng = []
for race_id, race_name, race_date in races:
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM race_entry WHERE race_id=%s", (race_id,))
    heads = c.fetchone()[0]
    c.execute("""SELECT COUNT(*), COUNT(face_comment) FROM stats_prediction
                 WHERE race_name=%s""", (race_name,))
    sp_total, sp_face = c.fetchone()
    c.execute("SELECT horse_name FROM race_entry WHERE race_id=%s", (race_id,))
    garbled = any(is_garbled(r[0]) for r in c.fetchall()) or is_garbled(race_name)
    c.close()

    ok = (heads > 0 and sp_total >= heads and sp_face >= heads and not garbled)
    status = "OK " if ok else "NG "
    if not ok:
        ng.append((race_id, race_name, heads, sp_total, sp_face, garbled))
    g = "有" if garbled else "-"
    safe_name = race_name if not garbled else "(bad)"
    print(f"  {status} {race_id:<13} {race_date} {heads:>4} {sp_total:>4} {sp_face:>4} {g:>4}  {safe_name}")

print(f"{'='*78}")
if ng:
    print(f"  要対応 {len(ng)}レース:")
    for race_id, name, h, t, f, g in ng:
        reason = []
        if g: reason.append("文字化け")
        if t < h: reason.append(f"統計不足({t}/{h})")
        if f < h: reason.append(f"顔面不足({f}/{h})")
        print(f"    race_id={race_id}  → {'/'.join(reason)}")
else:
    print("  全レース正常 OK")
print(f"{'='*78}\n")
cur.close()
conn.close()
