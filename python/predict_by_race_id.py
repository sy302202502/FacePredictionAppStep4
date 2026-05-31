"""
predict_by_race_id.py — race_id 指定で 統計予想 + 顔面分析を一括実行

使い方:
  python predict_by_race_id.py 202605021212
"""
import sys
import subprocess
import os
import psycopg2
from dotenv import load_dotenv

if len(sys.argv) < 2:
    print("使い方: python predict_by_race_id.py <race_id>")
    sys.exit(1)

race_id = sys.argv[1]
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

conn = psycopg2.connect(
    host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', '5432'),
    dbname=os.getenv('DB_NAME', 'faceapp'), user=os.getenv('DB_USER', 'postgres'),
    password=os.getenv('DB_PASSWORD', 'postgrestest')
)
cur = conn.cursor()
cur.execute("SELECT DISTINCT race_name FROM race_entry WHERE race_id = %s", (race_id,))
row = cur.fetchone()
conn.close()

if not row:
    print(f"❌ race_id={race_id} のデータが race_entry にありません")
    sys.exit(1)

race_name = row[0]
print(f"対象レース: {race_name} (race_id={race_id})")
print("=" * 60)

script_dir = os.path.dirname(os.path.abspath(__file__))

# 1. 統計予想
print("\n[1/2] 統計予想を実行...")
r1 = subprocess.run(
    ['python3', os.path.join(script_dir, 'stats_predictor.py'), race_name],
    cwd=script_dir
)
if r1.returncode != 0:
    print(f"❌ 統計予想失敗 (returncode={r1.returncode})")
    sys.exit(1)

# 2. 顔面分析
print("\n[2/2] 顔面分析を実行...")
r2 = subprocess.run(
    ['python3', os.path.join(script_dir, 'face_analyzer_local.py'), race_name],
    cwd=script_dir
)
if r2.returncode != 0:
    print(f"⚠️ 顔面分析失敗 (returncode={r2.returncode})")
    sys.exit(1)

print("\n" + "=" * 60)
print(f"✅ {race_name} の予想完了")
print(f"   → /predict-v2?raceName={race_name} で確認")
