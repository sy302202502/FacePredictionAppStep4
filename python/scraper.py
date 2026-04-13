"""
scraper.py
netkeibaから中央競馬の重賞レース結果を収集するスクリプト
  - 勝ち馬（1着）と負け馬（2〜5着）の両方を取得
  - レース種別（sprint/mile/middle/long/dirt）を自動判定
  - データ期間を最大15年まで対応

使い方: python scraper.py [取得年数(省略時=10)]
例:     python scraper.py 15
"""
import sys
import os
import time
import requests
import psycopg2
from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '../uploads/horses')

# -------------------------------------------------------
# レース種別判定
# -------------------------------------------------------
def classify_race(distance, surface):
    """距離と馬場からレース種別を判定"""
    if surface == 'ダート':
        return 'dirt'
    d = int(distance) if distance else 0
    if d <= 1400:
        return 'sprint'
    if d <= 1800:
        return 'mile'
    if d <= 2200:
        return 'middle'
    return 'long'

CATEGORY_LABEL = {
    'sprint': '短距離（〜1400m）',
    'mile':   'マイル（1600〜1800m）',
    'middle': '中距離（2000〜2200m）',
    'long':   '長距離（2400m〜）',
    'dirt':   'ダート',
}

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest')
    )

def fetch_grade_races(year):
    """netkeibaから指定年の重賞レース一覧を取得"""
    url = (
        f"https://db.netkeiba.com/?pid=race_list"
        f"&word=&start_year={year}&start_mon=1"
        f"&end_year={year}&end_mon=12"
        f"&jyo[]=01&jyo[]=02&jyo[]=03&jyo[]=04"
        f"&jyo[]=05&jyo[]=06&jyo[]=07&jyo[]=08"
        f"&jyo[]=09&jyo[]=10"
        f"&grade[]=1&grade[]=2&grade[]=3"
        f"&kyori_min=&kyori_max=&sort=date&list=100"
    )
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.encoding = 'EUC-JP'
    soup = BeautifulSoup(resp.text, 'lxml')

    races = []
    table = soup.find('table', class_='nk_tb_common')
    if not table:
        print(f"  [警告] {year}年のレース一覧テーブルが見つかりませんでした")
        return races

    for row in table.find_all('tr')[1:]:
        cols = row.find_all('td')
        if len(cols) < 5:
            continue
        try:
            race_link = cols[4].find('a')
            if not race_link:
                continue
            race_url = race_link.get('href', '')
            race_id = race_url.strip('/').split('/')[-1]
            race_name = race_link.text.strip()

            date_text = cols[0].text.strip()
            race_date = datetime.strptime(date_text, '%Y/%m/%d').date()

            grade = ''
            for g in ['G1', 'G2', 'G3']:
                if g in race_name:
                    grade = g
                    break

            venue = cols[1].text.strip() if len(cols) > 1 else ''
            races.append({
                'race_id': race_id,
                'race_name': race_name,
                'race_date': race_date,
                'grade': grade,
                'venue': venue,
            })
        except Exception:
            continue

    return races

def fetch_race_results(race_id):
    """
    レース結果ページから上位5頭の情報を取得
    戻り値: [{'rank': 1, 'horse_name': ..., 'horse_id': ...}, ...]
    距離と馬場も同時に取得
    """
    url = f"https://db.netkeiba.com/race/{race_id}/"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.encoding = 'EUC-JP'
    soup = BeautifulSoup(resp.text, 'lxml')

    # 距離・馬場を取得
    # 対応パターン例:
    #   芝右2500m / 芝右 外1400m / 芝右 内2周3600m / 芝 内-外3170m
    #   ダート右1800m / ダ右1200m / ダ左1600m
    distance = None
    surface = '芝'
    race_data = soup.find('div', class_='data_intro')
    if race_data:
        text = race_data.get_text()
        import re
        m = re.search(r'(芝|ダート|ダ)[右左外内直線\-\s]*(?:\d+周)?[右左外内\-\s]*(\d+)m', text)
        if m:
            raw_surface = m.group(1)
            surface = 'ダート' if raw_surface in ('ダ', 'ダート') else '芝'
            distance = int(m.group(2))

    result_table = soup.find('table', class_='race_table_01')
    if not result_table:
        return [], distance, surface

    results = []
    for row in result_table.find_all('tr')[1:]:
        cols = row.find_all('td')
        if not cols:
            continue
        try:
            rank_text = cols[0].text.strip()
            rank = int(rank_text)
        except ValueError:
            continue

        if rank > 5:
            continue

        horse_link = cols[3].find('a') if len(cols) > 3 else None
        if horse_link:
            horse_name = horse_link.text.strip()
            horse_url = horse_link.get('href', '')
            horse_id = horse_url.strip('/').split('/')[-1]
            results.append({'rank': rank, 'horse_name': horse_name, 'horse_id': horse_id})

    return results, distance, surface

def get_horse_photo_no(horse_id):
    """馬詳細ページから最初の写真番号を取得"""
    url = f"https://db.netkeiba.com/horse/{horse_id}/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'EUC-JP'
        soup = BeautifulSoup(resp.text, 'lxml')
        import re
        for img in soup.find_all('img'):
            src = img.get('src', '')
            m = re.search(r'show_photo\.php\?horse_id=\d+&no=(\d+)', src)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None

def download_horse_image(horse_id, horse_name):
    """馬の顔画像をダウンロードして保存"""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    save_path = os.path.join(UPLOAD_DIR, f"{horse_id}.jpg")

    if os.path.exists(save_path):
        return f"/uploads/horses/{horse_id}.jpg"

    try:
        photo_no = get_horse_photo_no(horse_id)
        if photo_no:
            url = f"https://db.netkeiba.com/show_photo.php?horse_id={horse_id}&no={photo_no}&tn=no&tmp=no"
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200 and len(resp.content) > 5000:
                with open(save_path, 'wb') as f:
                    f.write(resp.content)
                return f"/uploads/horses/{horse_id}.jpg"
    except Exception:
        pass

    return None

def save_race_result(conn, race, distance, surface, race_category):
    """レース情報をgrade_race_resultに保存（勝ち馬のみ）"""
    cur = conn.cursor()
    # 勝ち馬は呼び出し元で取得済み
    cur.close()

def upsert_race(conn, race, distance, surface, race_category, winner_name, winner_id, image_path, image_url):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO grade_race_result
            (race_id, race_name, race_date, grade, venue,
             distance, surface, race_category,
             winner_horse_name, winner_horse_id, image_url, image_path)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (race_id) DO UPDATE SET
            distance          = EXCLUDED.distance,
            surface           = EXCLUDED.surface,
            race_category     = EXCLUDED.race_category,
            winner_horse_name = EXCLUDED.winner_horse_name,
            winner_horse_id   = EXCLUDED.winner_horse_id,
            image_path        = EXCLUDED.image_path,
            image_url         = EXCLUDED.image_url
    """, (
        race['race_id'], race['race_name'], race['race_date'],
        race['grade'], race['venue'],
        distance, surface, race_category,
        winner_name, winner_id, image_url, image_path
    ))
    conn.commit()
    cur.close()

def upsert_horse_entry(conn, horse_id, horse_name, finish_rank, image_path, race_category):
    """
    horse_face_featureに馬のエントリを保存（分析前のスロット作成）
    is_winner: 1着のみTrue
    win_count: 1着の場合のみ加算
    """
    cur = conn.cursor()
    cur.execute("SELECT id, win_count FROM horse_face_feature WHERE horse_id = %s AND race_category = %s",
                (horse_id, race_category))
    row = cur.fetchone()

    is_winner = (finish_rank == 1)

    if row:
        if is_winner:
            cur.execute("""
                UPDATE horse_face_feature
                SET win_count = win_count + 1,
                    image_path = COALESCE(%s, image_path)
                WHERE horse_id = %s AND race_category = %s
            """, (image_path, horse_id, race_category))
        # 負け馬は出走回数だけ記録（win_countは変えない）
    else:
        cur.execute("""
            INSERT INTO horse_face_feature
                (horse_name, horse_id, image_path, finish_rank, race_category,
                 is_winner, win_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            horse_name, horse_id, image_path, finish_rank, race_category,
            is_winner, 1 if is_winner else 0
        ))

    conn.commit()
    cur.close()

def main():
    years = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    current_year = datetime.now().year
    target_years = list(range(current_year - years, current_year + 1))

    print(f"=== 中央競馬重賞スクレイピング開始 ({target_years[0]}〜{target_years[-1]}) ===")
    print(f"  取得対象: 1〜5着の馬（勝ち馬 + 負け馬）")
    conn = get_conn()

    for year in target_years:
        print(f"\n【{year}年】重賞レース一覧を取得中...")
        races = fetch_grade_races(year)
        print(f"  {len(races)}件のレースを発見")

        for i, race in enumerate(races):
            print(f"  [{i+1}/{len(races)}] {race['race_name']} ({race['race_date']}) {race['grade']}")
            try:
                results, distance, surface = fetch_race_results(race['race_id'])
                if not results:
                    print(f"    [スキップ] 結果情報なし")
                    time.sleep(1)
                    continue

                race_category = classify_race(distance, surface)
                print(f"    距離:{distance}m 馬場:{surface} 種別:{CATEGORY_LABEL.get(race_category)}")

                winner = next((r for r in results if r['rank'] == 1), None)
                if winner:
                    image_url = f"https://cdn.netkeiba.com/horse/pic/{winner['horse_id']}_l.jpg"
                    image_path = download_horse_image(winner['horse_id'], winner['horse_name'])
                    upsert_race(conn, race, distance, surface, race_category,
                                winner['horse_name'], winner['horse_id'], image_path, image_url)

                # 1〜5着全員を horse_face_feature に登録
                for entry in results:
                    img = download_horse_image(entry['horse_id'], entry['horse_name'])
                    upsert_horse_entry(conn, entry['horse_id'], entry['horse_name'],
                                       entry['rank'], img, race_category)
                    label = "勝ち馬" if entry['rank'] == 1 else f"{entry['rank']}着"
                    print(f"    {label}: {entry['horse_name']}")
                    time.sleep(0.5)

            except Exception as e:
                print(f"    [エラー] {e}")

            time.sleep(1.0)

    conn.close()
    print("\n=== スクレイピング完了 ===")

if __name__ == '__main__':
    main()
