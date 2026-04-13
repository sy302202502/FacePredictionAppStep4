"""
entry_fetcher.py
netkeibaから直近の重賞レースの出走馬一覧を自動取得してDBに保存するスクリプト

使い方:
  python entry_fetcher.py              # 今週末の重賞を全て取得
  python entry_fetcher.py "日本ダービー"  # レース名で絞り込み
"""
import sys
import os
import re
import time
import requests
import psycopg2
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '../uploads/candidates')

CATEGORY_MAP = {
    'sprint': '短距離（〜1400m）', 'mile': 'マイル（1600〜1800m）',
    'middle': '中距離（2000〜2200m）', 'long': '長距離（2400m〜）', 'dirt': 'ダート',
}

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'), user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest')
    )

def classify_race(distance, surface):
    if surface == 'ダート': return 'dirt'
    d = int(distance) if distance else 0
    if d <= 1400: return 'sprint'
    if d <= 1800: return 'mile'
    if d <= 2200: return 'middle'
    return 'long'

def fetch_upcoming_grade_races(query=None):
    """今週末〜2週間以内の重賞・OP・リステッドレース一覧を取得"""
    today = datetime.now()
    results = []
    for delta in range(0, 14):
        d = today + timedelta(days=delta)
        # race_list_sub.html は静的HTMLで返る（race_list.html はJS動的読み込み）
        url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={d.strftime('%Y%m%d')}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.encoding = 'utf-8'   # race_list_sub.html は UTF-8
            soup = BeautifulSoup(resp.text, 'lxml')
            for li in soup.find_all('li', class_='RaceList_DataItem'):
                # G1〜G3、OP、リステッドなど格付けレースをすべて対象
                grade_span = li.find('span', class_=re.compile(r'Icon_GradeType\d'))
                if not grade_span:
                    continue
                a = li.find('a', href=re.compile(r'shutuba'))
                if not a:
                    continue
                # レース名は ItemTitle span から取得
                title_span = li.find('span', class_='ItemTitle')
                race_name = title_span.text.strip() if title_span else a.text.strip().split('\n')[0]
                if query and query not in race_name:
                    continue
                href = a.get('href', '')
                m = re.search(r'race_id=(\d+)', href)
                race_id = m.group(1) if m else None
                if race_id:
                    results.append({'race_id': race_id, 'race_name': race_name, 'race_date': d.date()})
            time.sleep(0.5)
        except Exception as e:
            print(f"  [警告] {d.strftime('%Y%m%d')} の取得失敗: {e}")
    return results

def fetch_shutuba_entries(race_id):
    """出馬表ページから出走馬リストを取得"""
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.encoding = 'EUC-JP'
    soup = BeautifulSoup(resp.text, 'lxml')

    # 距離・馬場を取得
    distance, surface, grade, venue = None, '芝', '', ''
    race_data = soup.find('div', class_='RaceData01')
    if race_data:
        text = race_data.get_text()
        m = re.search(r'(芝|ダート)(\d+)m', text)
        if m:
            surface = m.group(1)
            distance = int(m.group(2))
    race_name_el = soup.find('div', class_='RaceName')
    race_name = race_name_el.text.strip() if race_name_el else ''
    venue_el = soup.find('span', class_='RaceData02')
    if venue_el:
        venue = venue_el.text.strip()[:10]

    entries = []
    table = soup.find('table', class_='Shutuba_Table')
    if not table:
        return entries, distance, surface, race_name, venue

    for row in table.find_all('tr', class_=re.compile(r'HorseList')):
        cols = row.find_all('td')
        if len(cols) < 5:
            continue
        try:
            post_pos   = cols[0].text.strip()
            horse_num  = cols[1].text.strip()
            horse_link = row.find('a', href=re.compile(r'/horse/'))
            if not horse_link:
                continue
            horse_name = horse_link.text.strip()
            horse_href = horse_link.get('href', '')
            horse_id_m = re.search(r'/horse/(\w+)', horse_href)
            horse_id   = horse_id_m.group(1) if horse_id_m else None
            jockey_link = row.find('a', href=re.compile(r'/jockey/'))
            jockey = jockey_link.text.strip() if jockey_link else ''
            entries.append({
                'post_position': int(post_pos) if post_pos.isdigit() else None,
                'horse_number':  int(horse_num) if horse_num.isdigit() else None,
                'horse_name': horse_name,
                'horse_id':   horse_id,
                'jockey_name': jockey,
            })
        except Exception:
            continue

    return entries, distance, surface, race_name, venue

def download_image(horse_id, horse_name):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    save_path = os.path.join(UPLOAD_DIR, f"{horse_id}.jpg")
    if os.path.exists(save_path):
        return f"/uploads/candidates/{horse_id}.jpg"
    for url_t in [
        f"https://cdn.netkeiba.com/horse/pic/{horse_id}_l.jpg",
        f"https://cdn.netkeiba.com/horse/pic/{horse_id}.jpg",
    ]:
        try:
            r = requests.get(url_t, headers=HEADERS, timeout=10)
            if r.status_code == 200 and len(r.content) > 5000:
                with open(save_path, 'wb') as f:
                    f.write(r.content)
                return f"/uploads/candidates/{horse_id}.jpg"
        except Exception:
            pass
    return None

def save_entries(conn, race_id, race_name, race_date, grade, venue, distance, surface, category, entries):
    cur = conn.cursor()
    try:
        # 既存のエントリを削除して入れ直す（同一トランザクション内）
        cur.execute("DELETE FROM race_entry WHERE race_id = %s", (race_id,))
        for e in entries:
            img = download_image(e['horse_id'], e['horse_name']) if e['horse_id'] else None
            cur.execute("""
                INSERT INTO race_entry
                    (race_id, race_name, race_date, race_category, grade, venue,
                     distance, surface, horse_name, horse_id,
                     post_position, horse_number, jockey_name, image_path)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (race_id, race_name, race_date, category, grade, venue,
                  distance, surface, e['horse_name'], e['horse_id'],
                  e['post_position'], e['horse_number'], e['jockey_name'], img))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()

def fetch_single_race(race_id, race_name, race_date):
    """race_idが分かっている場合に直接1レースを取得してDBに保存する"""
    conn = get_conn()
    try:
        print(f"【{race_name}】{race_date} race_id={race_id}")
        entries, distance, surface, scraped_name, venue = fetch_shutuba_entries(race_id)
        if not entries:
            print("  出走馬情報なし（まだ確定前の可能性）")
            return False
        category = classify_race(distance, surface)
        print(f"  {distance}m {surface} [{CATEGORY_MAP.get(category)}] {len(entries)}頭")
        save_entries(conn, race_id, scraped_name or race_name,
                     race_date, '', venue, distance, surface, category, entries)
        for e in entries:
            print(f"  {e['horse_number']}番 {e['horse_name']} ({e['jockey_name']})")
        return True
    except Exception as ex:
        print(f"  [エラー] {ex}")
        return False
    finally:
        conn.close()

def main():
    # --race-id オプション対応: race_id, race_name, race_date を直接指定
    if '--race-id' in sys.argv:
        idx = sys.argv.index('--race-id')
        race_id   = sys.argv[idx + 1]
        race_name = sys.argv[idx + 2] if idx + 2 < len(sys.argv) else race_id
        race_date = sys.argv[idx + 3] if idx + 3 < len(sys.argv) else str(datetime.now().date())
        print(f"=== 出走馬取得開始 (race_id直指定: {race_name}) ===")
        ok = fetch_single_race(race_id, race_name, race_date)
        if not ok:
            sys.exit(1)
        print("\n=== 取得完了 ===")
        return

    query = sys.argv[1] if len(sys.argv) > 1 else None
    print(f"=== 出走馬自動取得開始 {'(検索: ' + query + ')' if query else '(直近2週間の重賞)'} ===")

    races = fetch_upcoming_grade_races(query)
    if not races:
        print("対象レースが見つかりませんでした。")
        return

    print(f"{len(races)}件のレースを発見\n")
    conn = get_conn()

    for race_info in races:
        print(f"【{race_info['race_name']}】{race_info['race_date']} race_id={race_info['race_id']}")
        try:
            entries, distance, surface, race_name, venue = fetch_shutuba_entries(race_info['race_id'])
            if not entries:
                print("  出走馬情報なし（まだ確定前の可能性）")
                continue
            category = classify_race(distance, surface)
            print(f"  {distance}m {surface} [{CATEGORY_MAP.get(category)}] {len(entries)}頭")
            save_entries(conn, race_info['race_id'], race_name or race_info['race_name'],
                         race_info['race_date'], '', venue, distance, surface, category, entries)
            for e in entries:
                print(f"  {e['horse_number']}番 {e['horse_name']} ({e['jockey_name']})")
            time.sleep(1.0)
        except Exception as ex:
            print(f"  [エラー] {ex}")

    conn.close()
    print("\n=== 取得完了 ===")

if __name__ == '__main__':
    main()
