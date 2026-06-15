"""apply_indexes.py — インデックスを適用しテーブルを最適化する。
statement timeout（Supabase側）でパイプラインが失敗する問題の根本対策。
使い方: python apply_indexes.py
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

# インデックス作成は時間がかかるので statement_timeout を一時的に長く取る
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'), port=os.getenv('DB_PORT'),
    dbname=os.getenv('DB_NAME'), user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
    connect_timeout=20,
    options='-c statement_timeout=300000'  # 5分
)
conn.autocommit = True
cur = conn.cursor()

print("=== 適用前のテーブル規模 ===")
for t in ('race_entry', 'stats_prediction'):
    try:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"  {t}: {cur.fetchone()[0]:,} 行")
    except Exception as e:
        print(f"  {t}: 取得失敗 {e}")

sql_path = os.path.join(os.path.dirname(__file__), 'create_indexes.sql')
with open(sql_path, encoding='utf-8') as f:
    sql = f.read()

print("\n=== インデックス作成 ===")
for stmt in [s.strip() for s in sql.split(';') if s.strip() and not s.strip().startswith('--')]:
    # コメント行を除去
    body = '\n'.join(l for l in stmt.splitlines() if not l.strip().startswith('--')).strip()
    if not body:
        continue
    name = body.split('idx_')[1].split()[0] if 'idx_' in body else body[:40]
    try:
        cur.execute(body)
        print(f"  ✅ idx_{name}")
    except Exception as e:
        print(f"  ⚠️ idx_{name}: {e}")

print("\n=== ANALYZE（プランナ統計を更新）===")
for t in ('race_entry', 'stats_prediction'):
    try:
        cur.execute(f"ANALYZE {t}")
        print(f"  ✅ {t}")
    except Exception as e:
        print(f"  ⚠️ {t}: {e}")

cur.close()
conn.close()
print("\n完了。パイプラインのクエリが高速化されます。")
