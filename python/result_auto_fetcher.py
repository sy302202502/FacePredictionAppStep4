"""
result_auto_fetcher.py
レース後に実際の結果をnetkeibaからスクレイピングして的中記録を自動生成

【処理フロー】
  1. 予想データはあるが結果未記録のレースを検索
  2. grade_race_resultからrace_idを特定
  3. netkeibaから実際の着順をスクレイピング
  4. prediction_accuracy / race_specific_accuracy に記録
  5. 的中率サマリを表示

使い方:
  python result_auto_fetcher.py           # 全未記録レースを自動処理
  python result_auto_fetcher.py --dry-run # 対象レースの確認のみ
  python result_auto_fetcher.py --report  # 最新精度サマリを表示
"""
import sys
import os
import re
import time
import requests
import psycopg2
from bs4 import BeautifulSoup
from datetime import date
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest')
    )

def ensure_tables(conn):
    """race_specific_accuracy テーブルがなければ作成"""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_specific_accuracy (
            id SERIAL PRIMARY KEY,
            race_id VARCHAR(20),
            race_name VARCHAR(200),
            horse_name VARCHAR(100),
            predicted_rank INTEGER,
            actual_rank INTEGER,
            hit BOOLEAN DEFAULT FALSE,
            top5_hit BOOLEAN DEFAULT FALSE,
            score FLOAT,
            data_source VARCHAR(20) DEFAULT 'image',
            recorded_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()

# ------------------------------------------------------------------
# ① 未記録レースの検索
# ------------------------------------------------------------------
def find_unrecorded_old(conn):
    """prediction_resultにあるが的中記録がない過去レース"""
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT
            pr.target_race_name,
            pr.target_race_date,
            gr.race_id
        FROM prediction_result pr
        LEFT JOIN grade_race_result gr
            ON gr.race_name ILIKE '%%' || pr.target_race_name || '%%'
           AND ABS(gr.race_date - pr.target_race_date) <= 7
        WHERE NOT EXISTS (
            SELECT 1 FROM prediction_accuracy pa
            WHERE pa.race_name = pr.target_race_name
        )
        AND pr.target_race_date < (NOW() AT TIME ZONE 'Asia/Tokyo')::date  -- Supabase(UTC)対策
        ORDER BY pr.target_race_date DESC
        LIMIT 30
    """)
    rows = cur.fetchall()
    cur.close()
    return rows  # (race_name, race_date, race_id_or_None)

def find_unrecorded_new(conn):
    """race_specific_resultにあるが的中記録がない過去レース"""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_specific_accuracy (
            id SERIAL PRIMARY KEY,
            race_name VARCHAR(200),
            horse_name VARCHAR(100),
            predicted_rank INTEGER,
            actual_rank INTEGER,
            hit BOOLEAN DEFAULT FALSE,
            top5_hit BOOLEAN DEFAULT FALSE,
            score FLOAT,
            data_source VARCHAR(20),
            recorded_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    # grade_race_result に JOIN できなくても race_specific_result 単体で取得
    # created_at が2日以上前 = レース当日以降に記録されたと仮定
    # 日付の近い race_id のみ使用（±14日）して年違いを防ぐ
    cur.execute("""
        SELECT DISTINCT
            rsr.race_name,
            COALESCE(gr.race_date, (rsr.created_at::date + INTERVAL '1 day')::date) AS race_date,
            gr.race_id
        FROM race_specific_result rsr
        LEFT JOIN grade_race_result gr
            ON gr.race_name ILIKE '%%' || rsr.race_name || '%%'
            AND gr.race_date BETWEEN (rsr.created_at::date - INTERVAL '7 days')
                                 AND (rsr.created_at::date + INTERVAL '14 days')
        WHERE NOT EXISTS (
            SELECT 1 FROM race_specific_accuracy rsa
            WHERE rsa.race_name = rsr.race_name
        )
        AND rsr.created_at < NOW() - INTERVAL '1 day'
        ORDER BY race_date DESC NULLS LAST
        LIMIT 30
    """)
    rows = cur.fetchall()
    cur.close()
    return rows

# ------------------------------------------------------------------
# ② netkeibaから実際の着順を取得
# ------------------------------------------------------------------
def scrape_actual_results(race_id):
    """
    race_idを使ってnetkeibaから全着順を取得
    戻り値: {horse_name: finish_rank, ...}
    """
    if not race_id:
        return {}
    url = f"https://db.netkeiba.com/race/{race_id}/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'EUC-JP'
        soup = BeautifulSoup(resp.text, 'lxml')
    except Exception as e:
        print(f"    [スクレイピングエラー] {e}")
        return {}

    result_table = soup.find('table', class_='race_table_01')
    if not result_table:
        return {}

    results = {}
    for row in result_table.find_all('tr')[1:]:
        cols = row.find_all('td')
        if not cols:
            continue
        try:
            rank = int(cols[0].text.strip())
        except ValueError:
            continue
        horse_link = cols[3].find('a') if len(cols) > 3 else None
        if horse_link:
            results[horse_link.text.strip()] = rank
    return results

def search_race_id_by_name(conn, race_name, race_date=None):
    """race_nameからrace_idを検索。±180日以内のDBデータのみ使用し、なければnetkeibaを直接検索。"""
    cur = conn.cursor()
    if race_date:
        # 年違いデータを使わないよう ±180日以内に限定
        cur.execute("""
            SELECT race_id FROM grade_race_result
            WHERE race_name ILIKE %s
            AND ABS(race_date - %s::date) <= 180
            ORDER BY ABS(race_date - %s::date)
            LIMIT 1
        """, (f"%{race_name}%", str(race_date), str(race_date)))
    else:
        cur.execute("""
            SELECT race_id FROM grade_race_result
            WHERE race_name ILIKE %s
            ORDER BY race_date DESC
            LIMIT 1
        """, (f"%{race_name}%",))
    row = cur.fetchone()
    cur.close()
    if row:
        return row[0]

    # DBに見つからない場合はnetkeibaを直接検索
    return search_race_id_from_netkeiba(race_name, race_date)


def search_race_id_from_netkeiba(race_name, race_date=None):
    """netkeibaのレース検索でrace_idを取得（DBにない場合のフォールバック）"""
    from datetime import datetime, timedelta
    try:
        # 検索対象の年月を決定
        if race_date:
            if isinstance(race_date, str):
                dt = datetime.strptime(str(race_date)[:10], '%Y-%m-%d')
            elif hasattr(race_date, 'year'):
                dt = datetime(race_date.year, race_date.month, race_date.day)
            else:
                dt = datetime.today()
        else:
            dt = datetime.today()

        # 検索キーワードを生成（S→ステークス などの略称も正規化）
        kw_variants = [race_name]
        # 略称展開
        if race_name.endswith('S') or race_name.endswith('Ｓ'):
            base = race_name[:-1]
            kw_variants.append(base + 'ステークス')
            kw_variants.append(base)
        # 不要な記号除去
        kw_variants.append(re.sub(r'[Ｓ\s　]', '', race_name))

        # 当月と前後月を検索（最大3ヶ月）
        months_to_check = []
        for delta in [0, -1, 1]:
            m_dt = dt + timedelta(days=delta*30)
            months_to_check.append((m_dt.year, m_dt.month))

        for year, mon in months_to_check:
            url = (
                "https://db.netkeiba.com/?pid=race_search_detail"
                f"&start_year={year}&start_mon={mon}"
                f"&end_year={year}&end_mon={mon}"
                "&grade[]=1&grade[]=2&grade[]=3&grade[]=4&grade[]=5&grade[]=6"
                "&track[]=1&track[]=2&sort=date&list=500"
            )
            soup = None
            for attempt in range(3):
                try:
                    resp = requests.get(url, headers=HEADERS, timeout=15)
                    resp.encoding = 'EUC-JP'
                    soup = BeautifulSoup(resp.text, 'lxml')
                    break
                except Exception as e:
                    print(f"    [警告] netkeiba検索リクエスト失敗 attempt={attempt+1}: {e}")
                    if attempt < 2:
                        time.sleep(2 ** (attempt + 1))
            if soup is None:
                continue

            for a in soup.select('a[href*="/race/"]'):
                link_text = a.text.strip()
                href = a.get('href', '')
                m = re.search(r'/race/(\d{12})/?', href)
                if not m:
                    continue
                # いずれかのキーワードで部分一致
                if any(kw and kw in link_text for kw in kw_variants):
                    race_id = m.group(1)
                    print(f"    [netkeiba検索] {link_text} → race_id={race_id}")
                    return race_id

            time.sleep(1)

        print(f"    [netkeiba検索] '{race_name}' が見つかりませんでした")
        return None
    except Exception as e:
        print(f"    [netkeiba検索エラー] {e}")
        return None

# ------------------------------------------------------------------
# ③ 的中記録を保存
# ------------------------------------------------------------------
def record_old_system(conn, race_name, actual_results):
    """prediction_result → prediction_accuracy に記録"""
    if not actual_results:
        return 0
    cur = conn.cursor()
    cur.execute("""
        SELECT id, horse_name, rank_position, final_score, race_category, target_race_date
        FROM prediction_result
        WHERE target_race_name = %s
        ORDER BY rank_position
    """, (race_name,))
    predictions = cur.fetchall()
    if not predictions:
        cur.close()
        return 0

    race_date     = predictions[0][5]
    race_category = predictions[0][4]

    top5_names = [p[1] for p in predictions[:5]]
    actual_winner = next((name for name, rank in actual_results.items() if rank == 1), None)
    top5_hit = actual_winner in top5_names if actual_winner else False
    hit_1st = (predictions[0][1] == actual_winner) if actual_winner and predictions else False

    count = 0
    for pred_id, horse_name, pred_rank, final_score, cat, r_date in predictions:
        actual_rank = actual_results.get(horse_name)
        cur.execute("SELECT id FROM prediction_accuracy WHERE prediction_id = %s", (pred_id,))
        if cur.fetchone():
            cur.execute("""
                UPDATE prediction_accuracy
                SET actual_rank=%s, hit=%s, top5_hit=%s, recorded_at=NOW()
                WHERE prediction_id=%s
            """, (actual_rank, hit_1st and pred_rank == 1, top5_hit, pred_id))
        else:
            cur.execute("""
                INSERT INTO prediction_accuracy
                    (prediction_id, race_name, race_date, race_category,
                     horse_name, predicted_rank, actual_rank, hit, top5_hit, final_score)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (pred_id, race_name, race_date, cat,
                  horse_name, pred_rank, actual_rank,
                  hit_1st and pred_rank == 1, top5_hit, final_score))
        count += 1
    conn.commit()
    cur.close()
    return count

def find_unrecorded_stats(conn):
    """現行システム(stats_prediction)の予想があり、開催日を過ぎていて、
    まだ的中記録(data_source='stats')がないレースを race_id 基準で列挙する。
    race_id 突合なので年またぎ同名レースを誤って「記録済み」と判定しない。"""
    cur = conn.cursor()
    cur.execute("""
        SELECT sp.race_id, MIN(re.race_name), MIN(re.race_date)
        FROM stats_prediction sp
        JOIN race_entry re ON re.race_id = sp.race_id
        WHERE sp.race_id IS NOT NULL
          -- JST基準の「今日まで」を対象にする。CURRENT_DATE(サーバ=UTC)だと
          -- 土日夜のcronで当日レースが対象外になり、記録が翌朝まで遅れる。
          -- 当日でも結果未公開なら scrape が空を返しスキップ→次回再試行される。
          AND re.race_date <= (NOW() AT TIME ZONE 'Asia/Tokyo')::date
          AND NOT EXISTS (
              SELECT 1 FROM race_specific_accuracy rsa
              WHERE rsa.race_id = sp.race_id AND rsa.data_source = 'stats'
          )
        GROUP BY sp.race_id
        ORDER BY MIN(re.race_date) DESC
        LIMIT 30
    """)
    rows = cur.fetchall()
    cur.close()
    return rows

# ------------------------------------------------------------------
# Discord への答え合わせ投稿
#   判定は画面（/review）と同じ Java 側の結果を /review/api から受け取る
#   （固定保存の印・払戻表・買い目で判定済み。Python で同じ計算を持たない）
# ------------------------------------------------------------------
APP_URL = os.getenv('APP_INTERNAL_URL', 'http://app:8081')
PUBLIC_URL = os.getenv('APP_PUBLIC_URL', 'http://160.251.251.73:8081')


def fetch_review(race_id):
    try:
        r = requests.get(f"{APP_URL}/review/api", params={'raceId': race_id}, timeout=20)
        data = r.json() if r.status_code == 200 else {}
        return data if data.get('available') else None
    except Exception as e:
        print(f"    [通知] 答え合わせの取得に失敗 {race_id}: {e}")
        return None


def _review_line(v):
    rank = v.get('honmeiRank')
    hits = v.get('hitTypes') or []
    if not v.get('settled'):
        icon = '⏳'
    elif rank == 1:
        icon = '🏆'
    elif hits:
        icon = '✅'
    else:
        icon = '❌'
    num = f"{v['honmeiNumber']}番" if v.get('honmeiNumber') else ''
    line = f"{icon} **{v['raceName']}** ◎{num}{v['honmeiName']} " + (f"{rank}着" if rank else '着順なし')
    if hits:
        line += f" ｜ 的中: {'・'.join(hits)}"
    if v.get('payoutKnown') and v.get('invested'):
        ret = v.get('returnTotal') or 0
        line += f" ｜ 払戻 {ret:,}円（{round(ret * 100 / v['invested'])}%）"
    return line


def _discord_post(url, content):
    """1投稿を送る。429 は指示どおり待って再送、それ以外の失敗は例外にする（送信済み扱いにしない）"""
    for _ in range(3):
        resp = requests.post(url, json={'content': content}, timeout=10)
        if resp.status_code == 429:
            try:
                wait = min(30.0, float(resp.json().get('retry_after', 2)))
            except Exception:
                wait = 2.0
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return
    raise RuntimeError('Discord 429 が続いたため送信できませんでした')


def _send_discord(text):
    """Discord へ送る。1投稿2000字の上限に合わせ、行単位（長すぎる行はさらに分割）で送る。
    送れなかった場合は例外（呼び出し側で「未送信」のまま残し、次回再送する）。"""
    url = os.getenv('DISCORD_WEBHOOK_URL', '').strip()
    if not url:
        raise RuntimeError('DISCORD_WEBHOOK_URL 未設定')
    limit = 1800
    pieces = []
    for line in text.split('\n'):
        while len(line) > limit:
            pieces.append(line[:limit])
            line = line[limit:]
        pieces.append(line)
    chunk = ''
    for line in pieces:
        if chunk and len(chunk) + len(line) + 1 > limit:
            _discord_post(url, chunk)
            chunk = ''
        chunk += line + '\n'
    if chunk.strip():
        _discord_post(url, chunk)


def _this_weekend():
    """「この週末」の土曜・日曜（JST）。平日に実行したら直前の週末を指す"""
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone(timedelta(hours=9))).date()
    sat = today - timedelta(days=(today.weekday() - 5) % 7)
    return sat, sat + timedelta(days=1)


def notify_results(conn):
    """まだ Discord に送っていない答え合わせ（直近の週末分）と、週末の通算を送る。
    送信に成功したレースだけ discord_notified に記録するので、失敗しても次回の実行で再送される。"""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS discord_notified (
            race_id     VARCHAR(20) PRIMARY KEY,
            notified_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    sat, sun = _this_weekend()
    cur.execute("""
        SELECT DISTINCT rsa.race_id FROM race_specific_accuracy rsa
        JOIN race_entry re ON re.race_id = rsa.race_id
        WHERE rsa.data_source = 'stats' AND re.race_date BETWEEN %s AND %s
    """, (sat, sun))
    weekend_ids = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT race_id FROM discord_notified WHERE race_id = ANY(%s)", (weekend_ids,))
    done = {r[0] for r in cur.fetchall()}
    pending = [r for r in weekend_ids if r not in done]
    if not pending:
        cur.close()
        return

    reviews = {r: fetch_review(r) for r in weekend_ids}
    new = [(r, reviews[r]) for r in pending if reviews.get(r)]
    if not new:
        cur.close()
        return
    lines = [f"🎯 **鬼眼 答え合わせ速報**（{len(new)}レース）"]
    lines += [_review_line(v) for _, v in new]
    week = [v for v in reviews.values() if v]
    win = sum(1 for v in week if v.get('honmeiRank') == 1)
    place = sum(1 for v in week if v.get('honmeiRank') and v['honmeiRank'] <= 3)
    paid = [v for v in week if v.get('payoutKnown')]
    inv = sum(v['invested'] for v in paid)
    ret = sum(v.get('returnTotal') or 0 for v in paid)
    summary = f"\n📊 この週末（{sat.month}/{sat.day}〜{sun.month}/{sun.day}）{len(week)}レース: ◎1着 {win}・3着内 {place}"
    if inv:
        summary += f" ／ 投資 {inv:,}円 → 払戻 {ret:,}円（回収率 {round(ret * 100 / inv)}%）"
    lines.append(summary)
    lines.append(f"{PUBLIC_URL}/review")

    _send_discord('\n'.join(lines))   # 失敗したら例外 → 記録しない（次回再送）
    for r, _ in new:
        cur.execute("INSERT INTO discord_notified (race_id) VALUES (%s) ON CONFLICT DO NOTHING", (r,))
    conn.commit()
    cur.close()
    print(f"    [通知] Discord に {len(new)}レースの答え合わせを送信")


# 払戻の組番を正規化する。順序に意味がある券種（馬単・三連単）以外は昇順に並べる
ORDERED_BET_TYPES = ('馬単', '三連単')


def payout_key(bet_type, numbers):
    nums = [int(n) for n in numbers]
    if bet_type not in ORDERED_BET_TYPES:
        nums = sorted(nums)
    return '-'.join(str(n) for n in nums)


def parse_payouts(soup):
    """結果ページの払戻表 → [(券種, 組番キー, 払戻円, 人気)]。
    同着・複勝・ワイドの複数組もそのまま全行を返す（100円あたり）。"""
    rows = []
    for table in soup.find_all('table', class_='pay_table_01'):
        for tr in table.find_all('tr'):
            th = tr.find('th')
            tds = tr.find_all('td')
            if not th or len(tds) < 2:
                continue
            bet_type = th.get_text(strip=True)
            combos = [c for c in tds[0].get_text('|', strip=True).split('|') if c]
            pays = [p for p in tds[1].get_text('|', strip=True).split('|') if p]
            pops = [p for p in tds[2].get_text('|', strip=True).split('|')] if len(tds) > 2 else []
            for i, combo in enumerate(combos):
                nums = re.findall(r'\d+', combo)
                if not nums or i >= len(pays):
                    continue
                pay = int(re.sub(r'\D', '', pays[i]) or 0)
                pop = int(pops[i]) if i < len(pops) and pops[i].isdigit() else None
                rows.append((bet_type, payout_key(bet_type, nums), pay, pop))
    return rows


def ensure_payout_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_payout (
            id         SERIAL PRIMARY KEY,
            race_id    VARCHAR(20) NOT NULL,
            bet_type   VARCHAR(10) NOT NULL,
            combo      VARCHAR(20) NOT NULL,
            payout     INTEGER NOT NULL,
            popularity INTEGER,
            fetched_at TIMESTAMP DEFAULT NOW(),
            UNIQUE (race_id, bet_type, combo)
        )
    """)
    conn.commit()
    cur.close()


# 買い目（単勝・複勝・ワイド・馬連・三連複・三連単）の判定に必要な券種。
# 1つでも欠けた払戻表は部分取得とみなして保存しない（欠けた券種が「外れ」扱いになるため）
REQUIRED_BET_TYPES = ('単勝', '複勝', 'ワイド', '馬連', '三連複', '三連単')


def save_payouts(conn, race_id, payouts):
    """払戻を入れ替え保存（1トランザクション）。
    必要な券種がそろっていない払戻表は部分取得とみなし、既存の保存内容を残して何もしない。"""
    if not payouts:
        return 0
    got = {p[0] for p in payouts}
    missing = [t for t in REQUIRED_BET_TYPES if t not in got]
    if missing:
        print(f"    [保留] 払戻表に {'・'.join(missing)} がありません → 保存せず次回再取得")
        return 0
    cur = conn.cursor()
    cur.execute("DELETE FROM race_payout WHERE race_id = %s", (race_id,))
    for bet_type, combo, pay, pop in payouts:
        cur.execute("""
            INSERT INTO race_payout (race_id, bet_type, combo, payout, popularity)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (race_id, bet_type, combo) DO NOTHING
        """, (race_id, bet_type, combo, pay, pop))
    conn.commit()
    cur.close()
    return len(payouts)


def backfill_horse_numbers(conn, race_id, soup):
    """馬番が未反映（NULL）の出走馬に、結果ページの馬番を horse_id で埋める。
    出馬表同期を取りこぼしたレースでも、払戻との照合（馬番が必要）ができるようにする。"""
    table = soup.find('table', class_='race_table_01') if soup else None
    if not table:
        return 0
    nums = {}
    for row in table.find_all('tr')[1:]:
        cols = row.find_all('td')
        if len(cols) < 4:
            continue
        link = cols[3].find('a', href=re.compile(r'/horse/'))
        m_id = re.search(r'/horse/(\w+)', link.get('href', '')) if link else None
        num = cols[2].get_text(strip=True)
        if m_id and num.isdigit():
            nums[m_id.group(1)] = int(num)
    cur = conn.cursor()
    n = 0
    for hid, num in nums.items():
        cur.execute("UPDATE race_entry SET horse_number = %s WHERE race_id = %s AND horse_id = %s "
                    "AND horse_number IS NULL", (num, race_id, hid))
        n += cur.rowcount
        cur.execute("UPDATE stats_prediction SET horse_number = %s WHERE race_id = %s AND horse_id = %s "
                    "AND horse_number IS NULL", (num, race_id, hid))
    conn.commit()
    cur.close()
    return n


def fetch_result_page(race_id):
    """db.netkeiba の結果ページの soup。取れなければ None。"""
    try:
        resp = requests.get(f"https://db.netkeiba.com/race/{race_id}/", headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"    [スキップ] 結果ページ HTTP {resp.status_code}")
            return None
        resp.encoding = 'EUC-JP'
        return BeautifulSoup(resp.text, 'lxml')
    except Exception as e:
        print(f"    [スクレイピングエラー] {e}")
        return None


def scrape_actual_results_by_id(race_id, soup=None):
    """netkeiba の結果表から {horse_id: 着順} を取る。
    取消・除外・中止など数字でない着順の馬は含めない（着順なし）。
    馬名は表記揺れ・文字化けで予想側と一致しないことがあるため、現行システムは ID で突合する。"""
    if not race_id:
        return {}
    if soup is None:
        soup = fetch_result_page(race_id)
    if soup is None:
        return {}
    table = soup.find('table', class_='race_table_01')
    if not table:
        return {}
    results = {}
    for row in table.find_all('tr')[1:]:
        cols = row.find_all('td')
        if not cols:
            continue
        m_rank = re.match(r'(\d+)', cols[0].text.strip())  # 「3(降)」は降着後の着順
        link = cols[3].find('a', href=re.compile(r'/horse/')) if len(cols) > 3 else None
        m_id = re.search(r'/horse/(\w+)', link.get('href', '')) if link else None
        if m_rank and m_id:
            results[m_id.group(1)] = int(m_rank.group(1))
    return results


def record_stats_system(conn, race_id, race_name, actual_results):
    """stats_prediction(現行システム) → race_specific_accuracy に data_source='stats' で記録。
    予想の取得・既存記録の置換とも race_id 基準（同名別開催の誤記録・二重計上を防ぐ）。
    actual_results は {horse_id: 着順}。

    取得が不完全（1着が無い・予想馬の大半と突合できない）なら記録しない。
    記録済みになると二度と取り直されないため、半端な結果で確定させず次回に再試行させる。"""
    if not actual_results:
        return 0
    cur = conn.cursor()
    cur.execute("""
        SELECT horse_name, rank_position, score, horse_id
        FROM stats_prediction
        WHERE race_id = %s
        ORDER BY rank_position
    """, (race_id,))
    predictions = cur.fetchall()
    if not predictions:
        cur.close()
        return 0

    # 保存してよいのは結果が「完全」なときだけ（一度記録すると再取得されないため）:
    #   ・1〜3着がそろっている（同着なら 1,1,3 など）
    #   ・1〜3着の馬がすべて予想に含まれ、horse_id で突合できる（買い目判定に必須）
    #   ・着順の付いた馬の8割以上と突合できる（馬名変更・HTML部分取得などの異常検知）
    # 予想にいて結果表にいない馬は出走しなかった馬なので、actual_rank=NULL が正しい
    pred_ids = {p[3] for p in predictions if p[3]}
    podium = sorted((rank, hid) for hid, rank in actual_results.items() if rank <= 3)
    podium_ok = len(podium) >= 3 and podium[0][0] == 1
    podium_matched = all(hid in pred_ids for _, hid in podium)
    field_matched = sum(1 for hid in actual_results if hid in pred_ids)
    if not (podium_ok and podium_matched and field_matched >= len(actual_results) * 0.8):
        print(f"    [保留] 結果が不完全（1〜3着の突合={'OK' if podium_ok and podium_matched else 'NG'}"
              f"・出走{len(actual_results)}頭中{field_matched}頭一致）→ 記録せず次回再試行")
        cur.close()
        return 0

    top5_ids      = [p[3] for p in predictions[:5]]
    winner_ids    = {hid for hid, rank in actual_results.items() if rank == 1}  # 同着は複数
    top5_hit      = any(hid in winner_ids for hid in top5_ids)
    hit_1st       = predictions[0][3] in winner_ids

    # 再実行時は同一開催の既存記録を置き換える（二重計上防止）
    cur.execute("""
        DELETE FROM race_specific_accuracy
        WHERE race_id = %s AND data_source = 'stats'
    """, (race_id,))
    for horse_name, pred_rank, score, horse_id in predictions:
        actual_rank = actual_results.get(horse_id)
        # top5_hit は手動記録(AccuracyController)と同じ規約で「上位5頭の行のみ」保存
        cur.execute("""
            INSERT INTO race_specific_accuracy
                (race_id, race_name, horse_name, predicted_rank, actual_rank,
                 hit, top5_hit, score, data_source, recorded_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'stats',NOW())
        """, (race_id, race_name, horse_name, pred_rank, actual_rank,
              hit_1st and pred_rank == 1,
              top5_hit if pred_rank <= 5 else None, score))
    conn.commit()
    cur.close()
    return len(predictions)

def record_new_system(conn, race_name, actual_results):
    """race_specific_result → race_specific_accuracy に記録"""
    if not actual_results:
        return 0
    cur = conn.cursor()
    cur.execute("""
        SELECT horse_name, rank_position, score, data_source
        FROM race_specific_result
        WHERE race_name = %s
        ORDER BY rank_position
    """, (race_name,))
    predictions = cur.fetchall()
    if not predictions:
        cur.close()
        return 0

    top5_names   = [p[0] for p in predictions[:5]]
    actual_winner = next((name for name, rank in actual_results.items() if rank == 1), None)
    top5_hit     = actual_winner in top5_names if actual_winner else False
    hit_1st      = (predictions[0][0] == actual_winner) if actual_winner and predictions else False

    cur.execute("DELETE FROM race_specific_accuracy WHERE race_name = %s", (race_name,))
    for horse_name, pred_rank, score, data_src in predictions:
        actual_rank = actual_results.get(horse_name)
        cur.execute("""
            INSERT INTO race_specific_accuracy
                (race_name, horse_name, predicted_rank, actual_rank,
                 hit, top5_hit, score, data_source, recorded_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        """, (race_name, horse_name, pred_rank, actual_rank,
              hit_1st and pred_rank == 1, top5_hit, score, data_src))
    conn.commit()
    cur.close()
    return len(predictions)

# ------------------------------------------------------------------
# ④ 精度サマリ表示
# ------------------------------------------------------------------
def show_report(conn):
    cur = conn.cursor()
    print("\n" + "="*55)
    print("  予測精度レポート（自動記録分）")
    print("="*55)

    # 旧システム
    cur.execute("""
        SELECT COUNT(DISTINCT race_name),
               SUM(CASE WHEN hit=TRUE THEN 1 ELSE 0 END),
               SUM(CASE WHEN top5_hit=TRUE THEN 1 ELSE 0 END)
        FROM prediction_accuracy
        WHERE predicted_rank=1 AND top5_hit IS NOT NULL
    """)
    r = cur.fetchone()
    if r and r[0] and r[0] > 0:
        total, wh, t5h = r
        wh  = wh  or 0
        t5h = t5h or 0
        print(f"\n  【旧システム予想】")
        print(f"  記録済み: {total}レース  1位的中:{wh}回({wh/total*100:.1f}%)  TOP5:{t5h}回({t5h/total*100:.1f}%)")

    # 新システム（同名別年の開催を別レースとして数える: race_id優先）
    cur.execute("""
        SELECT COUNT(DISTINCT COALESCE(race_id, race_name)),
               SUM(CASE WHEN hit=TRUE THEN 1 ELSE 0 END),
               SUM(CASE WHEN top5_hit=TRUE THEN 1 ELSE 0 END)
        FROM race_specific_accuracy
        WHERE predicted_rank=1
    """)
    r2 = cur.fetchone()
    if r2 and r2[0] and r2[0] > 0:
        total, wh, t5h = r2
        wh  = wh  or 0
        t5h = t5h or 0
        print(f"\n  【顔面傾向分析予想（新）】")
        print(f"  記録済み: {total}レース  1位的中:{wh}回({wh/total*100:.1f}%)  TOP5:{t5h}回({t5h/total*100:.1f}%)")

    print("="*55)
    cur.close()

# ------------------------------------------------------------------
# メイン
# ------------------------------------------------------------------
def main():
    dry_run = '--dry-run' in sys.argv
    report  = '--report'  in sys.argv

    conn = get_conn()
    try:
        ensure_tables(conn)
        ensure_payout_table(conn)

        if report:
            show_report(conn)
            return

        print("=== 的中記録 自動取得 ===\n")

        old_races = find_unrecorded_old(conn)
        print(f"旧システム未記録: {len(old_races)}レース")

        for race_name, race_date, race_id in old_races:
            print(f"\n  [{race_name}] {race_date}")
            rid = race_id or search_race_id_by_name(conn, race_name, race_date)
            if not rid:
                print(f"    [スキップ] race_idが特定できません")
                continue
            if dry_run:
                print(f"    [dry-run] race_id={rid}")
                continue
            actual = scrape_actual_results(rid)
            if not actual:
                print(f"    [スキップ] 結果が取得できません (race_id={rid})")
                time.sleep(1)
                continue
            winner = next((n for n, r in actual.items() if r == 1), '不明')
            print(f"    実際の1着: {winner}  ({len(actual)}頭分取得)")
            n = record_old_system(conn, race_name, actual)
            print(f"    → {n}件記録完了")
            time.sleep(1.5)

        new_races = find_unrecorded_new(conn)
        print(f"\n新システム未記録: {len(new_races)}レース")

        for race_name, race_date, race_id in new_races:
            print(f"\n  [{race_name}] {race_date}")
            rid = race_id or search_race_id_by_name(conn, race_name, race_date)
            if not rid:
                print(f"    [スキップ] race_idが特定できません")
                continue
            if dry_run:
                print(f"    [dry-run] race_id={rid}")
                continue
            actual = scrape_actual_results(rid)
            if not actual:
                print(f"    [スキップ] 結果取得失敗")
                time.sleep(1)
                continue
            winner = next((n for n, r in actual.items() if r == 1), '不明')
            print(f"    実際の1着: {winner}")
            n = record_new_system(conn, race_name, actual)
            print(f"    → {n}件記録完了")
            time.sleep(1.5)

        # 現行システム（stats_prediction）の的中記録。
        # race_id が予想時点で確定しているため、検索も記録も race_id 直指定。
        stats_races = find_unrecorded_stats(conn)
        print(f"\n現行システム(stats)未記録: {len(stats_races)}レース")

        for race_id, race_name, race_date in stats_races:
            print(f"\n  [{race_name}] {race_date} (race_id={race_id})")
            if dry_run:
                print(f"    [dry-run]")
                continue
            soup = fetch_result_page(race_id)
            actual = scrape_actual_results_by_id(race_id, soup) if soup else {}
            if not actual:
                print(f"    [スキップ] 結果取得失敗")
                time.sleep(1)
                continue
            print(f"    {len(actual)}頭分の着順を取得")
            n = record_stats_system(conn, race_id, race_name, actual)
            if n:
                np_ = save_payouts(conn, race_id, parse_payouts(soup))
                nb = backfill_horse_numbers(conn, race_id, soup)
                print(f"    払戻 {np_}件を保存" + (f"・馬番 {nb}頭を補完" if nb else ""))
            print(f"    → {n}件記録完了")
            time.sleep(1.5)

        # 着順は記録済みだが払戻が未保存のレース（払戻機能の追加前に記録した分など）を埋める
        cur_p = conn.cursor()
        cur_p.execute("""
            SELECT DISTINCT rsa.race_id FROM race_specific_accuracy rsa
            WHERE rsa.data_source = 'stats' AND rsa.race_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM race_payout rp WHERE rp.race_id = rsa.race_id)
            LIMIT 60
        """)
        missing = [r[0] for r in cur_p.fetchall()]
        cur_p.close()
        if missing:
            print(f"\n払戻の未保存: {len(missing)}レース")
        for rid in missing:
            if dry_run:
                continue
            soup = fetch_result_page(rid)
            np_ = save_payouts(conn, rid, parse_payouts(soup)) if soup else 0
            nb = backfill_horse_numbers(conn, rid, soup) if soup else 0
            print(f"  {rid}: 払戻 {np_}件" + (f"・馬番 {nb}頭を補完" if nb else ""))
            time.sleep(1.5)

        if not dry_run:
            try:
                notify_results(conn)
            except Exception as e:
                conn.rollback()
                print(f"    [通知] 送信に失敗（記録は完了済み。次回の実行で再送）: {e}")

        if not dry_run:
            show_report(conn)
    finally:
        conn.close()
    print("\n=== 完了 ===")

if __name__ == '__main__':
    main()
