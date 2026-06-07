import psycopg2, os
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'), port=os.getenv('DB_PORT'),
    dbname=os.getenv('DB_NAME'), user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)
cur = conn.cursor()
cur.execute("SELECT race_id, race_name, race_date, COUNT(*) as cnt FROM race_entry WHERE race_date = CURRENT_DATE GROUP BY race_id, race_name, race_date ORDER BY race_name")
rows = cur.fetchall()
print(f"=== 本日のrace_entry ({len(rows)}件) ===")
for r in rows:
    print(f"  race_id={r[0]}  {r[2]}  {r[1]}  {r[3]}頭")
cur.close(); conn.close()
