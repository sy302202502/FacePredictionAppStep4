"""refix_all_garbled.py — 文字化けした全レースの馬名を一括修復する。
horse_id（文字化けしない）をキーに、正しい馬名へ張り替える。
顔面分析・スコアはそのまま保持（再分析なし・API消費ゼロ・高速）。

使い方:
  python refix_all_garbled.py            # 今日〜明日のレースを対象
  python refix_all_garbled.py --days 14  # 今日から14日以内を対象
"""
import sys, os
import psycopg2
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

from constants import is_garbled
from entry_fetcher import fetch_shutuba_entries, save_entries, classify_race

days = 1
if '--days' in sys.argv:
    days = int(sys.argv[sys.argv.index('--days') + 1])

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST'), port=os.getenv('DB_PORT'),
        dbname=os.getenv('DB_NAME'), user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        connect_timeout=15, options='-c statement_timeout=60000')

conn = get_conn()
cur = conn.cursor()
today = date.today()
cur.execute("""
    SELECT DISTINCT race_id, race_name, race_date
    FROM race_entry
    WHERE race_date BETWEEN %s AND %s
    ORDER BY race_date, race_id
""", (today, today + timedelta(days=days)))
races = cur.fetchall()
cur.close()
print(f"対象期間: {today} 〜 {today + timedelta(days=days)} / {len(races)}レース\n")

fixed, skipped, failed = 0, 0, 0
for race_id, old_name, race_date in races:
    # このレースに文字化けがあるか（race_entry もしくは stats_prediction）
    c = conn.cursor()
    c.execute("SELECT horse_name FROM race_entry WHERE race_id = %s", (race_id,))
    re_names = [r[0] for r in c.fetchall()]
    c.execute("SELECT horse_name FROM stats_prediction WHERE race_name = %s", (old_name,))
    sp_names = [r[0] for r in c.fetchall()]
    c.close()
    has_garble = any(is_garbled(n) for n in re_names + sp_names) or is_garbled(old_name)
    if not has_garble:
        skipped += 1
        continue

    print(f"race_id={race_id} 文字化け検出 → 修復中...")
    try:
        entries, distance, surface, scraped_name, venue = fetch_shutuba_entries(race_id)
        if not entries:
            print(f"   出馬表取得不可（未確定 or ガード）→ スキップ")
            failed += 1
            continue
        # horse_id → (正しい馬名, 馬番)
        mapping = {e['horse_id']: (e['horse_name'], e['horse_number'])
                   for e in entries if e.get('horse_id')}
        final_name = scraped_name or old_name

        # 1. race_entry を正しい名前で上書き
        category = classify_race(distance, surface)
        save_entries(conn, race_id, final_name, race_date, '', venue,
                     distance, surface, category, entries)

        # 2. stats_prediction の馬名・馬番・レース名を horse_id で張り替え（顔面データは保持）
        c = conn.cursor()
        updated = 0
        for hid, (name, num) in mapping.items():
            c.execute("""
                UPDATE stats_prediction
                SET horse_name = %s, horse_number = %s, race_name = %s
                WHERE horse_id = %s AND race_name = %s
            """, (name, num, final_name, hid, old_name))
            updated += c.rowcount
        conn.commit()
        c.close()
        print(f"   OK {final_name}: race_entry {len(entries)}頭 / stats_prediction {updated}頭 修復")
        fixed += 1
    except Exception as e:
        print(f"   失敗: {e}")
        conn.rollback()
        failed += 1

conn.close()
print(f"\n{'='*50}")
print(f"  修復: {fixed}レース / 正常スキップ: {skipped} / 失敗: {failed}")
print(f"{'='*50}")
