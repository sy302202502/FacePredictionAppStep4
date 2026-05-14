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

def fetch_horse_numbers(race_id):
    """シュツバ表から 馬番→(horse_name, horse_id) マッピングを取得"""
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'EUC-JP'
        soup = BeautifulSoup(resp.text, 'lxml')
    except Exception as e:
        print(f"  [エラー] シュツバ取得失敗: {e}")
        return {}

    mapping = {}
    # 馬番セルとHorseNameスパンを同一行から取得
    for row in soup.find_all('tr'):
        # 馬番セル
        num_td = None
        for td in row.find_all('td'):
            cls = ' '.join(td.get('class', []))
            if re.match(r'Umaban\d*', cls) and td.text.strip().isdigit():
                num_td = td
                break
        if not num_td:
            continue
        horse_num = int(num_td.text.strip())

        horse_a = row.find('a', href=re.compile(r'db\.netkeiba\.com/horse/\d+'))
        if not horse_a:
            continue
        horse_name = horse_a.get('title') or horse_a.text.strip()
        m = re.search(r'/horse/(\d+)', horse_a['href'])
        horse_id = m.group(1) if m else None
        mapping[horse_num] = (horse_name, horse_id)

    return mapping

def fetch_odds_api(race_id):
    """JSON APIから単勝オッズ・人気を取得。{馬番str: (odds_float, pop_int)}"""
    url = f"https://race.netkeiba.com/api/api_get_jra_odds.html?race_id={race_id}&type=1&action=update"
    try:
        resp = requests.get(url, headers={**HEADERS, 'Referer': 'https://race.netkeiba.com/'}, timeout=15)
        data = resp.json()
    except Exception as e:
        print(f"  [エラー] オッズAPI失敗: {e}")
        return {}

    if data.get('status') not in ('middle', 'final', 'fixed'):
        print(f"  [スキップ] APIステータス: {data.get('status')} (発売前の可能性)")
        return {}

    raw = data.get('data', {}).get('odds', {}).get('1', {})
    result = {}
    for num_str, vals in raw.items():
        try:
            odds_val = float(vals[0])
            pop = int(vals[2]) if vals[2] else 0
            result[int(num_str)] = (odds_val, pop)
        except Exception:
            continue
    return result

def save_odds(conn, race_id, race_name, horse_map, odds_map):
    cur = conn.cursor()
    cur.execute("DELETE FROM race_odds WHERE race_id = %s", (race_id,))
    for horse_num, (odds_val, pop) in odds_map.items():
        info = horse_map.get(horse_num)
        if not info:
            continue
        horse_name, horse_id = info
        cur.execute("""
            INSERT INTO race_odds (race_id, race_name, horse_name, horse_id, win_odds, popularity, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """, (race_id, race_name, horse_name, horse_id, odds_val, pop))
    conn.commit()
    cur.close()

def main():
    query = sys.argv[1] if len(sys.argv) > 1 else None
    conn  = get_conn()
    ensure_table(conn)
    cur = conn.cursor()

    if query:
        cur.execute("SELECT DISTINCT race_id, race_name FROM race_entry WHERE race_name ILIKE %s",
                    (f"%{query}%",))
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
        odds_map  = fetch_odds_api(race_id)
        if not odds_map:
            continue
        horse_map = fetch_horse_numbers(race_id)
        if not horse_map:
            print("  [警告] 馬番マッピング取得失敗")
            continue
        save_odds(conn, race_id, race_name, horse_map, odds_map)
        for horse_num in sorted(odds_map.keys()):
            odds_val, pop = odds_map[horse_num]
            name = horse_map.get(horse_num, ('不明',))[0]
            print(f"    {pop}人気 {horse_num}番 {name}: {odds_val}倍")
        time.sleep(1.5)

    conn.close()
    print("=== 完了 ===")

if __name__ == '__main__':
    main()
