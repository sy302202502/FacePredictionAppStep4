"""refix_race.py — 文字化けしたレースを完全復旧する。
出馬表を正しいエンコーディングで取り直し→統計予想→顔面分析を一括実行。
使い方: python refix_race.py 202602010411
"""
import sys, os, subprocess
import psycopg2
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

if len(sys.argv) < 2:
    print("使い方: python refix_race.py <race_id>")
    sys.exit(1)
race_id = sys.argv[1]

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST'), port=os.getenv('DB_PORT'),
        dbname=os.getenv('DB_NAME'), user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        connect_timeout=15, options='-c statement_timeout=60000')

# 1. 出馬表を正しいエンコーディングで取り直す（race_entryを上書き）
from entry_fetcher import fetch_shutuba_entries, save_entries, classify_race
print(f"[1/4] 出馬表を再取得（race_id={race_id}）...")
entries, distance, surface, scraped_name, venue = fetch_shutuba_entries(race_id)
if not entries:
    print("❌ 出馬表が取得できません（未確定 or 文字化けガード作動）。中止します。")
    sys.exit(1)

# 取り直した名前で race_date を引き継ぐ
conn = get_conn()
cur = conn.cursor()
cur.execute("SELECT race_date FROM race_entry WHERE race_id = %s LIMIT 1", (race_id,))
row = cur.fetchone()
race_date = row[0] if row else None
old_name = None
cur.execute("SELECT DISTINCT race_name FROM race_entry WHERE race_id = %s", (race_id,))
r2 = cur.fetchone()
old_name = r2[0] if r2 else None
cur.close()

category = classify_race(distance, surface)
final_name = scraped_name or old_name
print(f"  → 正しい名前: {final_name} / {len(entries)}頭 {distance}m{surface}")
save_entries(conn, race_id, final_name, race_date, '', venue, distance, surface, category, entries)

# 2. 旧名のstats_predictionが残っていれば掃除（名前が変わった場合の孤児データ削除）
if old_name and old_name != final_name:
    c = conn.cursor()
    c.execute("DELETE FROM stats_prediction WHERE race_name = %s", (old_name,))
    print(f"[2/4] 旧名の予想 {c.rowcount}件を削除（{old_name} → {final_name}）")
    conn.commit(); c.close()
else:
    print("[2/4] 旧名と同一のためスキップ")
conn.close()

# 3. 統計予想＋image_path＋顔面分析（predict_by_race_id が一括実行）
print(f"[3/3] 統計予想＋顔面分析を実行...")
r = subprocess.run(['python3', os.path.join(SCRIPT_DIR, 'predict_by_race_id.py'), race_id], cwd=SCRIPT_DIR)
print(f"\n{'✅ 完全復旧しました' if r.returncode == 0 else '⚠️ 顔面分析でエラー（再実行可）'}: race_id={race_id}")
