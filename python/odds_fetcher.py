"""
odds_fetcher.py
netkeibaから当日の単勝オッズ・人気を取得してDBに保存

使い方:
  python odds_fetcher.py "日本ダービー"   # 指定レースのオッズを取得
  python odds_fetcher.py                   # race_entryにある全レースのオッズを取得
"""
import sys
import os
import re
import time
import requests
import psycopg2
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest')
    )

def ensure_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_odds (
            id SERIAL PRIMARY KEY,
            race_id VARCHAR(20),
            race_name VARCHAR(200),
            horse_name VARCHAR(100),
            horse_id VARCHAR(20),
            win_odds FLOAT,
            popularity INTEGER,
            fetched_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()

def fetch_odds_from_page(race_id):
    """
    netkeibaの単勝オッズページからオッズを取得
    戻り値: {horse_name: {'odds': float, 'popularity': int}, ...}
    """
    url = f"https://race.netkeiba.com/odds/index.html?race_id={race_id}&type=b1"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'EUC-JP'
        soup = BeautifulSoup(resp.text, 'lxml')
    except Exception as e:
        print(f"  [エラー] オッズページ取得失敗: {e}")
        return {}

    results = {}
    # 単勝オッズテーブルを探す
    table = soup.find('table', id='odds_tan_block') or soup.find('table', class_=re.compile(r'Odds'))
    if not table:
        # 別のセレクターを試す
        divs = soup.find_all('tr', class_=re.compile(r'HorseList'))
        for row in divs:
            cols = row.find_all('td')
            if len(cols) < 5:
                continue
            horse_link = row.find('a', href=re.compile(r'/horse/'))
            if not horse_link:
                continue
            horse_name = horse_link.text.strip()
            # オッズ列を探す
            for col in cols:
                txt = col.text.strip()
                if re.match(r'^\d+\.\d+$', txt):
                    try:
                        results[horse_name] = {'odds': float(txt), 'popularity': 0}
                    except Exception:
                        pass
                    break
        return results

    for row in table.find_all('tr')[1:]:
        cols = row.find_all('td')
        if len(cols) < 3:
            continue
        try:
            horse_link = row.find('a', href=re.compile(r'/horse/'))
            if not horse_link:
                continue
            horse_name = horse_link.text.strip()
            # 人気順位（最初のtd）
            pop_text = cols[0].text.strip()
            pop = int(pop_text) if pop_text.isdigit() else 0
            # オッズ（数値のtd）
            odds_val = None
            for col in cols:
                txt = col.text.strip().replace(',', '')
                if re.match(r'^\d+\.\d+$', txt):
                    odds_val = float(txt)
                    break
            if odds_val:
                results[horse_name] = {'odds': odds_val, 'popularity': pop}
        except Exception:
            continue

    return results

def save_odds(conn, race_id, race_name, odds_dict):
    cur = conn.cursor()
    cur.execute("DELETE FROM race_odds WHERE race_id = %s", (race_id,))
    for horse_name, info in odds_dict.items():
        # horse_idをrace_entryから検索
        cur.execute("SELECT horse_id FROM race_entry WHERE race_name ILIKE %s AND horse_name = %s LIMIT 1",
                    (f"%{race_name}%", horse_name))
        row = cur.fetchone()
        horse_id = row[0] if row else None
        cur.execute("""
            INSERT INTO race_odds (race_id, race_name, horse_name, horse_id, win_odds, popularity, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """, (race_id, race_name, horse_name, horse_id,
              info['odds'], info['popularity']))
    conn.commit()
    cur.close()

def main():
    query = sys.argv[1] if len(sys.argv) > 1 else None
    conn  = get_conn()
    ensure_table(conn)
    cur = conn.cursor()

    # race_entryからrace_id取得
    if query:
        cur.execute("""
            SELECT DISTINCT race_id, race_name FROM race_entry
            WHERE race_name ILIKE %s
        """, (f"%{query}%",))
    else:
        cur.execute("SELECT DISTINCT race_id, race_name FROM race_entry ORDER BY race_name")
    races = cur.fetchall()
    cur.close()

    if not races:
        print("対象レースが見つかりません。先に entry_fetcher.py を実行してください。")
        conn.close()
        return

    print(f"=== オッズ取得: {len(races)}レース ===")
    for race_id, race_name in races:
        print(f"  [{race_name}] race_id={race_id}")
        odds = fetch_odds_from_page(race_id)
        if odds:
            save_odds(conn, race_id, race_name, odds)
            for name, info in sorted(odds.items(), key=lambda x: x[1]['popularity'] or 99):
                print(f"    {info['popularity']}人気 {name}: {info['odds']}倍")
        else:
            print(f"    [スキップ] オッズ未確定（発売前の可能性）")
        time.sleep(1.5)

    conn.close()
    print("=== 完了 ===")

if __name__ == '__main__':
    main()
