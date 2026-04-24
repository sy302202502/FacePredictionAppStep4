"""
high_dividend_selector.py
週末の全出走レースから「最も高配当が狙えるレース」を1レース厳選し、
顔面予想を実行する目玉機能スクリプト。

使い方:
  python3 python/high_dividend_selector.py                    # 今週末を対象
  python3 python/high_dividend_selector.py --date 20260426    # 日付指定
"""

import sys
import os
import re
import json
import time
import math
import subprocess
import requests
import psycopg2
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, date
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

# chaos_score の重み
W_FAVORITE_ODDS = 3.0    # 1番人気オッズ
W_HORSE_COUNT   = 1.5    # 出走頭数
W_ODDS_STD      = 2.0    # オッズ標準偏差
W_MID_ODDS      = 1.0    # 3〜5番人気の平均オッズ

# 重賞ペナルティ
GRADE_PENALTY = {'G1': -20, 'G2': -10, 'G3': -5}

# 汎用クラス名（顔面分析が機能しない）には大きなペナルティ
GENERIC_RACE_RE = re.compile(
    r'(\d歳(?:以上)?(?:未勝利|\d勝クラス|障害(?:未勝利|オープン|OP))|新馬|未出走)'
)
GENERIC_PENALTY = -200

# 5頭未満のレースは除外
MIN_HORSE_COUNT = 5

# 1番人気オッズがこの値未満のレースは万馬券候補から除外（本命が強すぎるレース）
MIN_FAVORITE_ODDS = 2.5

# 一般戦は頭数が多い上位N件のみ対象
MAX_NON_GRADE_RACES = 20


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
        CREATE TABLE IF NOT EXISTS high_dividend_selection (
            id SERIAL PRIMARY KEY,
            race_id VARCHAR(20),
            race_name VARCHAR(200),
            venue VARCHAR(50),
            race_date DATE,
            horse_count INTEGER,
            favorite_odds DOUBLE PRECISION,
            odds_variance DOUBLE PRECISION,
            chaos_score DOUBLE PRECISION,
            selection_reason TEXT,
            top5_json TEXT,
            analyzed_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()


# ------------------------------------------------------------------
# Step1: 週末のレース一覧取得
# ------------------------------------------------------------------

def get_target_dates(base_date_str=None):
    """今週末（土日）の日付リストを返す。base_date_strが指定されればその日のみ。"""
    if base_date_str:
        try:
            d = datetime.strptime(base_date_str, '%Y%m%d').date()
            return [d]
        except ValueError:
            print(f"  [警告] 日付形式が不正です: {base_date_str}。今週末を使用します。")

    today = date.today()
    # 今日から7日以内の土日を探す
    weekend_dates = []
    for delta in range(8):
        d = today + timedelta(days=delta)
        if d.weekday() in (5, 6):  # 5=土, 6=日
            weekend_dates.append(d)
        if len(weekend_dates) == 2:
            break
    return weekend_dates


def parse_grade_from_class(li):
    """li要素からIcon_GradeType系classを解析してグレードを返す。"""
    grade_span = li.find('span', class_=re.compile(r'Icon_GradeType\d'))
    if not grade_span:
        return None
    cls_list = grade_span.get('class', [])
    for cls in cls_list:
        m = re.search(r'Icon_GradeType(\d+)', cls)
        if m:
            n = int(m.group(1))
            # Icon_GradeType1=G1, 2=G2, 3=G3, 4=OP, 5=Listed, ...
            if n == 1:
                return 'G1'
            elif n == 2:
                return 'G2'
            elif n == 3:
                return 'G3'
            elif n == 4:
                return 'OP'
            elif n == 5:
                return 'L'
            else:
                return 'GRADE'
    return 'GRADE'


def fetch_all_races_for_date(target_date):
    """
    race_list_sub.html から指定日の全レース情報を取得。
    戻り値: list of dict {race_id, race_name, race_date, grade, is_grade_race}
    """
    url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={target_date.strftime('%Y%m%d')}"
    races = []
    non_grade_races = []

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'lxml')

        for li in soup.find_all('li', class_='RaceList_DataItem'):
            a = li.find('a', href=re.compile(r'shutuba'))
            if not a:
                continue
            href = a.get('href', '')
            m = re.search(r'race_id=(\d+)', href)
            if not m:
                continue
            race_id = m.group(1)

            title_span = li.find('span', class_='ItemTitle')
            race_name = title_span.text.strip() if title_span else a.text.strip().split('\n')[0]

            grade = parse_grade_from_class(li)
            is_grade = grade is not None

            # 頭数を取得（RaceList_Item05_Num などから取れる場合）
            horse_count_text = ''
            for span in li.find_all('span'):
                t = span.text.strip()
                m2 = re.search(r'(\d+)頭', t)
                if m2:
                    horse_count_text = int(m2.group(1))
                    break

            info = {
                'race_id': race_id,
                'race_name': race_name,
                'race_date': target_date,
                'grade': grade or '',
                'is_grade_race': is_grade,
                'horse_count_hint': horse_count_text or 0,
            }

            if is_grade:
                races.append(info)
            else:
                non_grade_races.append(info)

    except Exception as e:
        print(f"  [警告] {target_date.strftime('%Y%m%d')} の取得失敗: {e}")

    # 一般戦は頭数ヒントで降順ソートして上位MAX件のみ
    non_grade_races.sort(key=lambda x: x['horse_count_hint'], reverse=True)
    races.extend(non_grade_races[:MAX_NON_GRADE_RACES])

    return races


# ------------------------------------------------------------------
# Step2: オッズ取得
# ------------------------------------------------------------------

def fetch_odds_info(race_id):
    """
    netkeiba オッズJSON APIから単勝オッズを取得し、人気順にソートされたオッズリストを返す。
    ※ネケイバのオッズ表示はJavaScriptで動的ロードされるため、HTMLスクレイピングではなく
      内部APIを直接呼び出す方式に変更。

    戻り値: list of {'horse_name': str, 'odds': float, 'popularity': int}
            取得失敗時は None
    """
    api_headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': f'https://race.netkeiba.com/odds/index.html?race_id={race_id}&type=b1',
    }

    # --- Step A: 馬番→馬名 マッピングを取得 ---
    # 枠確定済みレース: オッズHTMLから col1=馬番(01,02,..) → col4=馬名
    # 枠未確定レース: shutubaのtr_IDが内部エントリIDとなりAPIキーと一致する
    horse_map = {}  # API key → 馬名

    html_url = f"https://race.netkeiba.com/odds/index.html?race_id={race_id}&type=b1"
    try:
        resp = requests.get(html_url, headers=api_headers, timeout=15)
        resp.encoding = 'EUC-JP'
        soup = BeautifulSoup(resp.text, 'lxml')
        table = soup.find('table', class_='RaceOdds_HorseList_Table')
        if table:
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) < 5:
                    continue
                num_txt = cols[1].text.strip()  # col1 = 馬番
                name_txt = cols[4].text.strip()  # col4 = 馬名
                if num_txt.isdigit() and name_txt:
                    horse_map[num_txt.zfill(2)] = name_txt  # '01' → name
    except Exception:
        pass

    # 枠確定前（horse_mapが空）の場合: 出馬表のtr_IDで紐付け
    # （枠未確定時、APIキーはゼロパディングなしの内部エントリIDと一致）
    if not horse_map:
        shutuba_url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
        try:
            resp2 = requests.get(shutuba_url, headers=api_headers, timeout=15)
            resp2.encoding = 'EUC-JP'
            soup2 = BeautifulSoup(resp2.text, 'lxml')
            shutuba_table = soup2.find('table', class_='Shutuba_Table')
            if shutuba_table:
                for row in shutuba_table.find_all('tr', class_=re.compile(r'HorseList')):
                    tr_id = row.get('id', '')  # 'tr_21', 'tr_1', ...
                    horse_link = row.find('a', href=re.compile(r'/horse/'))
                    if tr_id.startswith('tr_') and horse_link:
                        entry_id = tr_id[3:]  # '21', '1', ...
                        horse_map[entry_id] = horse_link.text.strip()
        except Exception:
            pass

    # --- Step B: JSON APIから単勝オッズを取得 ---
    api_url = (
        f"https://race.netkeiba.com/api/api_get_jra_odds.html"
        f"?race_id={race_id}&type=1&action=init"
    )
    try:
        api_resp = requests.get(api_url, headers=api_headers, timeout=15)
        api_data = api_resp.json()
        odds_raw = api_data['data']['odds']['1']  # '1' = 単勝
    except Exception:
        return None

    results = []
    for horse_num_str, vals in odds_raw.items():
        try:
            odds_val = float(vals[0])
            popularity = int(vals[2]) if len(vals) > 2 and str(vals[2]) not in ('0', '') else 0
            if odds_val <= 1.0:
                continue
            # 枠確定レース: APIキー '01' → horse_map['01']
            # 枠未確定レース: APIキー '19' → horse_map['19'] (shutuba tr_id)
            horse_name = (horse_map.get(horse_num_str)
                          or horse_map.get(horse_num_str.lstrip('0') or '0')
                          or f'馬番{int(horse_num_str)}')
            results.append({'horse_name': horse_name, 'odds': odds_val, 'popularity': popularity})
        except (ValueError, IndexError, TypeError):
            continue

    if not results:
        return None

    # 人気順でソート（0は末尾）
    results.sort(key=lambda x: x['popularity'] if x['popularity'] > 0 else 999)
    return results


# ------------------------------------------------------------------
# Step3: 荒れスコア計算
# ------------------------------------------------------------------

def calc_chaos_score(odds_list, grade):
    """
    odds_list: [{horse_name, odds, popularity}, ...]  人気順
    grade: 'G1' / 'G2' / 'G3' / 'OP' / 'L' / ''
    """
    if not odds_list or len(odds_list) < MIN_HORSE_COUNT:
        return None, {}

    # 1番人気オッズが低すぎるレースは万馬券候補から除外
    if odds_list[0]['odds'] < MIN_FAVORITE_ODDS:
        return None, {}

    odds_values = [h['odds'] for h in odds_list]
    horse_count = len(odds_values)

    # 1番人気オッズ（人気順1位）
    favorite_odds = odds_list[0]['odds']

    # オッズ標準偏差
    mean = sum(odds_values) / horse_count
    variance = sum((o - mean) ** 2 for o in odds_values) / horse_count
    std_dev = math.sqrt(variance)

    # 3〜5番人気の平均オッズ
    mid_range = odds_list[2:5]  # index 2,3,4 = 3〜5番人気
    mid_avg = sum(h['odds'] for h in mid_range) / len(mid_range) if mid_range else 0

    # 重賞ペナルティ
    grade_pen = GRADE_PENALTY.get(grade, 0)

    score = (
        (favorite_odds * W_FAVORITE_ODDS)
        + (horse_count * W_HORSE_COUNT)
        + (std_dev * W_ODDS_STD)
        + (mid_avg * W_MID_ODDS)
        + grade_pen
    )

    detail = {
        'favorite_odds': favorite_odds,
        'horse_count': horse_count,
        'odds_std': std_dev,
        'odds_variance': variance,
        'mid_avg': mid_avg,
        'grade_penalty': grade_pen,
        'chaos_score': score,
    }

    return score, detail


def apply_generic_penalty(race_name, score):
    """汎用クラス名（3歳未勝利等）には顔面分析が機能しないためペナルティを付加。"""
    if GENERIC_RACE_RE.search(race_name):
        return score + GENERIC_PENALTY
    return score


# ------------------------------------------------------------------
# Step5: 選定理由生成
# ------------------------------------------------------------------

def build_selection_reason(race_name, detail, odds_list, grade):
    parts = []
    fav = detail['favorite_odds']
    count = detail['horse_count']
    std = detail['odds_std']

    if fav >= 10.0:
        parts.append(f"1番人気が{fav:.1f}倍の大混戦")
    elif fav >= 5.0:
        parts.append(f"1番人気でも{fav:.1f}倍と混戦模様")
    else:
        parts.append(f"1番人気{fav:.1f}倍")

    parts.append(f"{count}頭立て")

    if std >= 15.0:
        parts.append("オッズ分散も最大級")
    elif std >= 8.0:
        parts.append("オッズのばらつき大")

    if grade in GRADE_PENALTY:
        parts.append(f"({grade}重賞・重賞補正適用)")

    # TOP5オッズ
    top5 = odds_list[:5]
    top5_str = '、'.join(f"{h['horse_name']}({h['odds']}倍)" for h in top5)
    reason = '、'.join(parts) + f"。上位5頭: {top5_str}"

    return reason


# ------------------------------------------------------------------
# Step4 & Step7: 出走馬登録と shutuba スクレイピング
# ------------------------------------------------------------------

def fetch_shutuba_entries(race_id):
    """出馬表ページから出走馬リスト・レース情報を取得。"""
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'EUC-JP'
        soup = BeautifulSoup(resp.text, 'lxml')
    except Exception as e:
        return [], None, '芝', '', ''

    distance, surface, venue = None, '芝', ''
    race_data = soup.find('div', class_='RaceData01')
    if race_data:
        text = race_data.get_text()
        m = re.search(r'(芝|ダート)(\d+)m', text)
        if m:
            surface = m.group(1)
            distance = int(m.group(2))

    race_name_el = soup.find('div', class_='RaceName')
    scraped_race_name = race_name_el.text.strip() if race_name_el else ''

    venue_el = soup.find('span', class_='RaceData02')
    if venue_el:
        venue = venue_el.text.strip()[:10]

    entries = []
    table = soup.find('table', class_='Shutuba_Table')
    if not table:
        return entries, distance, surface, scraped_race_name, venue

    for row in table.find_all('tr', class_=re.compile(r'HorseList')):
        cols = row.find_all('td')
        if len(cols) < 5:
            continue
        try:
            post_pos = cols[0].text.strip()
            horse_num = cols[1].text.strip()
            horse_link = row.find('a', href=re.compile(r'/horse/'))
            if not horse_link:
                continue
            horse_name = horse_link.text.strip()
            horse_href = horse_link.get('href', '')
            horse_id_m = re.search(r'/horse/(\w+)', horse_href)
            horse_id = horse_id_m.group(1) if horse_id_m else None
            jockey_link = row.find('a', href=re.compile(r'/jockey/'))
            jockey = jockey_link.text.strip() if jockey_link else ''
            entries.append({
                'post_position': int(post_pos) if post_pos.isdigit() else None,
                'horse_number': int(horse_num) if horse_num.isdigit() else None,
                'horse_name': horse_name,
                'horse_id': horse_id,
                'jockey_name': jockey,
            })
        except Exception:
            continue

    return entries, distance, surface, scraped_race_name, venue


def classify_race(distance, surface):
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


UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '../uploads/candidates')


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


def save_entries_to_db(conn, race_id, race_name, race_date, grade, venue, distance, surface, category, entries):
    cur = conn.cursor()
    try:
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


# ------------------------------------------------------------------
# Step6: DB保存
# ------------------------------------------------------------------

def save_selection(conn, best, detail, reason, top5_json_str):
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO high_dividend_selection
                (race_id, race_name, venue, race_date, horse_count,
                 favorite_odds, odds_variance, chaos_score, selection_reason, top5_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            best['race_id'],
            best['race_name'],
            best.get('venue', ''),
            best['race_date'],
            detail['horse_count'],
            detail['favorite_odds'],
            detail['odds_variance'],
            detail['chaos_score'],
            reason,
            top5_json_str,
        ))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


# ------------------------------------------------------------------
# メイン処理
# ------------------------------------------------------------------

def main():
    # --date オプション
    base_date_str = None
    if '--date' in sys.argv:
        idx = sys.argv.index('--date')
        if idx + 1 < len(sys.argv):
            base_date_str = sys.argv[idx + 1]

    # ---- Step1 ----
    print("[Step1] 週末レース一覧を取得中...")
    target_dates = get_target_dates(base_date_str)
    if not target_dates:
        print("  [エラー] 対象日が見つかりませんでした。")
        sys.exit(1)

    all_races = []
    date_summary = []
    for d in target_dates:
        races_for_day = fetch_all_races_for_date(d)
        all_races.extend(races_for_day)
        wday = '土' if d.weekday() == 5 else '日' if d.weekday() == 6 else d.strftime('%a')
        date_summary.append(f"{d.strftime('%Y-%m-%d')}({wday}): {len(races_for_day)}レース")
        time.sleep(0.5)

    print(f"  → {', '.join(date_summary)}")

    if not all_races:
        print("  [エラー] レースが見つかりませんでした。")
        sys.exit(1)

    # ---- Step2 ----
    print(f"[Step2] 各レースのオッズを取得中... ({len(all_races)}レース)")

    scored_races = []
    for race_info in all_races:
        odds_list = fetch_odds_info(race_info['race_id'])
        if not odds_list:
            time.sleep(0.5)
            continue

        score, detail = calc_chaos_score(odds_list, race_info['grade'])
        if score is None:
            time.sleep(0.5)
            continue

        # 汎用クラス名には顔面分析不可ペナルティを付加
        adjusted_score = apply_generic_penalty(race_info['race_name'], score)

        race_info['odds_list'] = odds_list
        race_info['detail'] = detail
        race_info['chaos_score'] = adjusted_score

        generic_note = ' [汎用レース-ペナルティ]' if adjusted_score != score else ''
        print(f"  → {race_info['race_name']}: 1番人気={detail['favorite_odds']}倍, "
              f"{detail['horse_count']}頭, 混戦度={adjusted_score:.1f}{generic_note}")

        scored_races.append(race_info)
        time.sleep(0.5)

    if not scored_races:
        print("  [エラー] スコア計算できるレースがありませんでした。")
        sys.exit(1)

    # ---- Step3 ----
    print("[Step3] 高配当レースを厳選中...")
    scored_races.sort(key=lambda x: x['chaos_score'], reverse=True)
    best = scored_races[0]
    detail = best['detail']
    odds_list = best['odds_list']

    print(f"  🎯 厳選完了: {best['race_name']} (混戦度スコア: {best['chaos_score']:.1f})")

    # DB接続（Step4で馬名補完後にreasonを生成するため、先に接続だけ確立）
    conn = get_conn()
    ensure_table(conn)

    # ---- Step4 ----
    print("[Step4] 出走馬をrace_entryに登録中...")
    entries, distance, surface, scraped_name, venue = fetch_shutuba_entries(best['race_id'])

    # race_nameは元のレース名をそのまま使用（仕様通り）
    final_race_name = best['race_name']
    if not entries:
        print("  [警告] 出走馬情報を取得できませんでした（出馬表未確定の可能性）")
    else:
        category = classify_race(distance, surface)
        # venue が shutuba から取れた場合は更新
        if scraped_name:
            final_race_name = scraped_name  # shutubaからの正式名称を優先

        # shutuba エントリから 馬番→馬名 マッピングを作り、odds_list の馬名を補完
        entry_num_to_name = {
            e['horse_number']: e['horse_name']
            for e in entries if e.get('horse_number') and e.get('horse_name')
        }
        for h in odds_list:
            if h['horse_name'].startswith('馬番'):
                try:
                    num = int(h['horse_name'].replace('馬番', ''))
                    if num in entry_num_to_name:
                        h['horse_name'] = entry_num_to_name[num]
                except ValueError:
                    pass

        save_entries_to_db(conn, best['race_id'], final_race_name, best['race_date'],
                           best['grade'], venue or '', distance, surface, category, entries)
        print(f"  → {len(entries)}頭を登録完了")

    # 馬名が補完されたので選定理由を生成
    reason = build_selection_reason(final_race_name, detail, odds_list, best['grade'])
    print(f"  理由: {reason}")
    top5_json_str = json.dumps(
        [{'horse_name': h['horse_name'], 'odds': h['odds'], 'popularity': h['popularity']}
         for h in odds_list[:5]],
        ensure_ascii=False
    )

    # DB保存 (Step6)
    save_selection(conn, best, detail, reason, top5_json_str)
    conn.close()

    # ---- Step5 ----
    print("[Step5] 顔面分析を開始します...")
    analyzer_path = os.path.join(os.path.dirname(__file__), 'race_specific_analyzer.py')
    cmd = ['python3', analyzer_path, final_race_name, '7']
    print(f"  → {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            print(line, end='', flush=True)
        proc.wait()
    except Exception as e:
        print(f"  [エラー] 顔面分析の起動に失敗しました: {e}")

    print("=== 厳選完了 ===")
    print(f"SELECTED_RACE:{final_race_name}")


if __name__ == '__main__':
    main()
