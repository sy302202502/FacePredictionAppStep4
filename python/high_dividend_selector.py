"""
high_dividend_selector.py
レース当日のレースから「最も高配当が狙えるレース」を1レース厳選する（万馬券チャレンジ）。

  1. 候補 = 予想済みのレース（単勝オッズはオッズの自動取得が DB に入れたもの）
           ＋ まだ予想していない「特別・OP」のうち頭数の多い最大 EXTRA_RACES レース
             （レース一覧を1回、単勝オッズを1レース1回ずつ、1つの接続で読む）
  2. 荒れやすさ（混戦度スコア）で1レースを選ぶ
  3. 選んだレースがまだ予想されていなければ、そのレースだけ出馬表・統計予想・顔面分析を作る
     （毎朝のパイプラインと同じ手順。パイプライン実行中は終わるのを待つ）

netkeiba への負荷対策（BAN回避）:
  ・オッズのAPIは1つの接続（Cookie）あたり5〜6回で「user update limit」を返す（2026-10-18 確認）。
    接続を作り直してこの制限を外すことはしない。読むのは上限内の最大 EXTRA_RACES レースだけ
  ・limit やアクセス拒否（403/429/503）が返ったら、その場で読むのをやめて読めた分で選ぶ
  ・1日（実際に読む日）の読み取り回数は DB（high_dividend_fetch）で1回ごとに先に確保し、失敗・--dry-run・--force も含めて1日 DAILY_REQUEST_CAP 回まで。
    使い切った日は netkeiba を読まずに予想済みのレースだけで選ぶ
  ・選定は1日1回だけ。その日の選定が済んでいれば読みに行かない（--force を除く）。
    予想画面を作れなかった日は、次の実行でオッズは読み直さずに予想作成だけをやり直す
  ・同時に2つ動かない（cron と画面のボタンが重なっても、後から来た方は何もせずに終わる）

使い方:
  python3 python/high_dividend_selector.py                    # 今日
  python3 python/high_dividend_selector.py --date 20261018    # 日付指定
  python3 python/high_dividend_selector.py --force            # その日の選定をやり直す（手動のみ。オッズを読み直す）
  python3 python/high_dividend_selector.py --dry-run          # 選ぶだけ（DB保存・予想作成をしない）
  python3 python/high_dividend_selector.py --retry-only       # 予想画面を作れなかった選定の予想作成だけやり直す（netkeiba のオッズは読まない）
"""

import sys
import os
import re
import json
import time
import math
import random
import fcntl
import requests
import psycopg2
from bs4 import BeautifulSoup
from datetime import datetime, date
from dotenv import load_dotenv
from constants import HEADERS

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

import weekly_pipeline as wp

# chaos_score の重み
W_FAVORITE_ODDS = 3.0    # 1番人気オッズ
W_HORSE_COUNT   = 1.5    # 出走頭数
W_SPLIT         = 60.0   # 人気の割れ具合（単勝オッズから求めた勝率分布の正規化エントロピー 0〜1）
W_MID_ODDS      = 1.0    # 3〜5番人気の平均オッズ
MID_ODDS_CAP    = 20.0   # 3〜5番人気の平均オッズの評価上限（倍）

# 重賞ペナルティ
GRADE_PENALTY = {'G1': -20, 'G2': -10, 'G3': -5}

# 汎用クラス名（顔面分析が機能しない）には大きなペナルティ
GENERIC_RACE_RE = re.compile(
    r'(\d歳(?:以上)?(?:未勝利|\d勝クラス|障害(?:未勝利|オープン|OP))|障害\d歳(?:以上)?(?:未勝利|オープン|OP)|新馬|未出走)'
)
GENERIC_PENALTY = -200

# 5頭未満のレースは除外
MIN_HORSE_COUNT = 5

# 1番人気オッズがこの値未満のレースは万馬券候補から除外（本命が強すぎるレース）
MIN_FAVORITE_ODDS = 2.5

# 取れたオッズの頭数が出走頭数のこの割合に満たないレースは候補にしない（一部の馬しか取れていない）
MIN_ODDS_COVERAGE = 0.8

# 予想していないレースから足す候補の数（オッズAPIの1接続あたりの上限 5〜6回 に収める）
EXTRA_RACES = 5
# netkeiba の読み取り（一覧1 + Cookie取得1 + オッズ EXTRA_RACES）の1日の上限と間隔
DAILY_REQUEST_CAP = 2 + EXTRA_RACES
REQUEST_INTERVAL = (2.5, 3.5)

# 毎朝のパイプラインが動いている間は予想作成を待つ。待つのはこの時刻まで
# （子処理は各15分まで。11時の出馬表同期とぶつからないように。間に合わなければ 11:20 の回でやり直す）
PIPELINE_WAIT_UNTIL = (10, 15)

# 選定そのものの二重起動を防ぐ
SELECTOR_LOCK = '/tmp/high_dividend_selector.lock'


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def get_conn():
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest')
    )
    conn.autocommit = True
    return conn


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
    # 全レース方式（2026-10）で追加: 何レースから選んだか・予想画面ができているか
    cur.execute("""
        CREATE TABLE IF NOT EXISTS high_dividend_fetch (
            race_date DATE PRIMARY KEY,
            requests INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("ALTER TABLE high_dividend_selection ADD COLUMN IF NOT EXISTS race_number INTEGER")
    cur.execute("ALTER TABLE high_dividend_selection ADD COLUMN IF NOT EXISTS candidate_count INTEGER")
    cur.execute("ALTER TABLE high_dividend_selection ADD COLUMN IF NOT EXISTS source VARCHAR(20)")
    # 既定値なし: 以前の行は NULL（予想画面ができているか不明）のままにして「準備中」と表示しない
    cur.execute("ALTER TABLE high_dividend_selection ADD COLUMN IF NOT EXISTS prediction_ready BOOLEAN")
    cur.close()


def reserve_request(conn, target_date):
    """今日の読み取り枠を1つ確保する（原子的）。上限に達していれば False"""
    cur = conn.cursor()
    cur.execute("""INSERT INTO high_dividend_fetch (race_date, requests) VALUES (%s, 1)
                   ON CONFLICT (race_date) DO UPDATE
                   SET requests = high_dividend_fetch.requests + 1, updated_at = NOW()
                   WHERE high_dividend_fetch.requests < %s
                   RETURNING requests""", (target_date, DAILY_REQUEST_CAP))
    ok = cur.fetchone() is not None
    cur.close()
    return ok


VENUES = {'01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
          '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'}


def venue_of(race_id):
    return VENUES.get(race_id[4:6], '')


def race_number_of(race_id):
    return int(race_id[-2:]) if race_id[-2:].isdigit() else None


# ------------------------------------------------------------------
# netkeiba の読み取り（回数を数え、断られたら止める）
# ------------------------------------------------------------------

class Blocked(Exception):
    """アクセスを断られた／上限に達した。これ以上 netkeiba を読まない"""


class Reader:
    """1回読むたびに、その前に DB で今日の枠を1つ確保する（途中で強制終了しても1日の上限を超えない）。
    枠は「実際に読む日」で数える（--date で別の日を指定しても、同じ日に2重に枠を使えないように）"""
    def __init__(self, conn):
        self.conn = conn
        self.target_date = date.today()
        self.count = 0
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def get(self, url, referer=None, limit_text=None):
        """limit_text: 応答にこの文字があれば制限とみなして止める（小文字で比較）"""
        if not reserve_request(self.conn, self.target_date):
            raise Blocked(f'今日の読み取りの上限（{DAILY_REQUEST_CAP}回）に達しました')
        if self.count:
            time.sleep(random.uniform(*REQUEST_INTERVAL))
        self.count += 1
        headers = {'Referer': referer} if referer else None
        resp = self.session.get(url, headers=headers, timeout=15)
        if resp.status_code in (403, 429, 503):
            raise Blocked(f'アクセスを断られました（HTTP {resp.status_code}）')
        if limit_text and limit_text in resp.text.lower():
            raise Blocked(f'読み取りの制限がかかりました（{limit_text}）')
        return resp


def parse_grade_from_class(li):
    """li要素からIcon_GradeType系classを解析してグレードを返す。"""
    grade_span = li.find('span', class_=re.compile(r'Icon_GradeType\d'))
    if not grade_span:
        return ''
    m = re.search(r'Icon_GradeType(\d+)', ' '.join(grade_span.get('class', [])))
    n = int(m.group(1)) if m else 0
    return {1: 'G1', 2: 'G2', 3: 'G3', 4: 'OP', 5: 'L'}.get(n, 'GRADE')


def fetch_race_list(reader, target_date):
    """その日の全レース。開催が無い日は []。正常なページでなければ None"""
    url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={target_date.strftime('%Y%m%d')}"
    resp = reader.get(url)
    resp.encoding = 'utf-8'
    # 正常な一覧ページには、開催の無い日でも目印がある（weekly_pipeline と同じ判定）
    if 'race_list_sub' not in resp.text or 'RaceList_Box' not in resp.text:
        return None
    soup = BeautifulSoup(resp.text, 'lxml')
    races, seen = [], set()
    for li in soup.find_all('li', class_='RaceList_DataItem'):
        a = li.find('a', href=re.compile(r'race_id=\d+'))
        m = a and re.search(r'race_id=(\d{12})', a.get('href', ''))
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        title = li.find('span', class_='ItemTitle')
        heads = re.search(r'(\d+)頭', li.get_text())
        races.append({
            'race_id': m.group(1),
            'race_name': title.text.strip() if title else a.text.strip().split('\n')[0],
            'race_date': target_date,
            'grade': parse_grade_from_class(li),
            'horse_count_hint': int(heads.group(1)) if heads else 0,
        })
    return races


def fetch_win_odds(reader, race_id, why=None):
    """単勝オッズ → [{'umaban', 'odds', 'popularity'}]（オッズの低い順）。発売前・取れないときは None。
    why（dict）を渡すと、取れなかった理由ごとの件数を入れる"""
    def fail(reason):
        if why is not None:
            why[reason] = why.get(reason, 0) + 1
        return None
    url = (f"https://race.netkeiba.com/api/api_get_jra_odds.html"
           f"?race_id={race_id}&type=1&action=update")
    referer = f'https://race.netkeiba.com/odds/index.html?race_id={race_id}&type=b1'
    resp = reader.get(url, referer=referer, limit_text='limit')
    if resp.status_code != 200 or not resp.text.strip():
        return fail(f'HTTP {resp.status_code}' if resp.status_code != 200 else '空の応答')
    try:
        data = resp.json()
    except ValueError:
        # 想定外のページ（制限・エラーの画面など）。読み続けずに止める
        raise Blocked('オッズのAPIが想定外の応答を返しました')
    if data.get('status') == 'limit':
        raise Blocked(f"オッズの読み取り上限に達しました（{data.get('reason') or 'limit'}）")
    if data.get('status') not in ('middle', 'final', 'fixed'):
        return fail(f"状態 {data.get('status')}")   # result=確定済み（発走後）など
    try:
        raw = data['data']['odds']['1']
    except (KeyError, TypeError):
        return fail('単勝オッズなし')
    out = []
    for num, vals in raw.items():
        try:
            odds = float(vals[0])
            pop = int(vals[2]) if len(vals) > 2 and str(vals[2]) not in ('0', '') else 0
        except (ValueError, IndexError, TypeError):
            continue
        if odds > 1.0:   # 取消・除外は 0 や --- で返る
            out.append({'umaban': int(num), 'odds': odds, 'popularity': pop})
    # 人気順＝単勝オッズの低い順（発売初期は人気順位が 0 で返るため）
    out.sort(key=lambda h: h['odds'])
    return out or fail('有効なオッズなし')


def enough_odds(odds_list, heads):
    """出走頭数に対して、オッズが十分な頭数そろっているか（頭数が分からないときは取れた分で判断）"""
    if not odds_list:
        return False
    return not heads or len(odds_list) >= heads * MIN_ODDS_COVERAGE


def odds_from_db(conn, target_date):
    """予想済みのレース（race_entry）と、オッズの自動取得（odds_fetcher）がDBに入れた単勝オッズ"""
    cur = conn.cursor()
    cur.execute("""
        SELECT re.race_id, MAX(re.race_name), MAX(re.grade), COUNT(*)
        FROM race_entry re WHERE re.race_date = %s GROUP BY re.race_id
    """, (target_date,))
    races = []
    for race_id, name, grade, heads in cur.fetchall():
        cur.execute("""
            SELECT ro.win_odds, ro.popularity, ro.horse_name, re.horse_number
            FROM race_odds ro
            LEFT JOIN race_entry re ON re.race_id = ro.race_id AND re.horse_id = ro.horse_id
            WHERE ro.race_id = %s AND ro.win_odds > 1.0
              -- レース当日に取ったオッズだけ（取得に失敗した日の古い行・翌日以降の行で選ばない）
              AND ro.fetched_at >= %s AND ro.fetched_at < %s::date + INTERVAL '1 day'
        """, (race_id, target_date, target_date))
        odds = [{'umaban': num, 'odds': o, 'popularity': p or 0, 'horse_name': hn}
                for o, p, hn, num in cur.fetchall()]
        odds.sort(key=lambda h: h['odds'])
        races.append({'race_id': race_id, 'race_name': name, 'race_date': target_date,
                      'grade': grade if grade in ('G1', 'G2', 'G3', 'OP', 'L') else '',
                      'horse_count_hint': heads,
                      'odds_list': odds if enough_odds(odds, heads) else None})
    cur.close()
    return races


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

    # オッズ分散（DB互換のため記録のみ。スコアには使わない）
    mean = sum(odds_values) / horse_count
    variance = sum((o - mean) ** 2 for o in odds_values) / horse_count
    std_dev = math.sqrt(variance)

    # 人気の割れ具合: 単勝オッズ→勝率(1/オッズを合計1に正規化)のエントロピーを頭数で正規化。
    # 1.0 に近いほど「どの馬にも勝つ可能性がある」混戦。
    # 標準偏差は、1〜2頭が抜けた人気で残りが大穴という本命決着型でも大きくなり、
    # 混戦の指標としては逆向きになり得たため置き換えた
    implied = [1.0 / o for o in odds_values]
    total = sum(implied)
    probs = [p / total for p in implied]
    split = -sum(p * math.log(p) for p in probs if p > 0) / math.log(horse_count)

    # 3〜5番人気の平均オッズ（上限 MID_ODDS_CAP 倍で頭打ち）。
    # 3〜5番人気が20倍を超えるのは上位2頭の一騎打ち＝本命決着型で、混戦ではない。
    # 上限なしだと大穴ぞろいの本命レースほど加点されていた
    mid_range = odds_list[2:5]  # index 2,3,4 = 3〜5番人気
    mid_avg = sum(h['odds'] for h in mid_range) / len(mid_range) if mid_range else 0
    mid_avg = min(mid_avg, MID_ODDS_CAP)

    # 重賞ペナルティ
    grade_pen = GRADE_PENALTY.get(grade, 0)

    score = (
        (favorite_odds * W_FAVORITE_ODDS)
        + (horse_count * W_HORSE_COUNT)
        + (split * W_SPLIT)
        + (mid_avg * W_MID_ODDS)
        + grade_pen
    )

    detail = {
        'favorite_odds': favorite_odds,
        'horse_count': horse_count,
        'odds_std': std_dev,
        'odds_split': split,
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
    split = detail['odds_split']

    if fav >= 10.0:
        parts.append(f"1番人気が{fav:.1f}倍の大混戦")
    elif fav >= 5.0:
        parts.append(f"1番人気でも{fav:.1f}倍と混戦模様")
    else:
        parts.append(f"1番人気{fav:.1f}倍")

    parts.append(f"{count}頭立て")

    if split >= 0.9:
        parts.append("人気が大きく割れている")
    elif split >= 0.8:
        parts.append("人気が割れ気味")

    if grade in GRADE_PENALTY:
        parts.append(f"({grade}重賞・重賞補正適用)")

    # TOP5オッズ
    top5 = odds_list[:5]
    top5_str = '、'.join(f"{h['horse_name']}({h['odds']}倍)" for h in top5)
    reason = '、'.join(parts) + f"。上位5頭: {top5_str}"

    return reason




# ------------------------------------------------------------------
# 選んだレースの予想を作る（毎朝のパイプラインと同じ手順）
# ------------------------------------------------------------------

def wait_pipeline_lock():
    """毎朝のパイプラインと同時に出馬表取得・顔面分析を走らせない。終わるまで待ってロックを取る"""
    f = open(wp.LOCK_FILE, 'a')   # 'w' だと実行中のパイプラインが書いた PID を消してしまう
    now = datetime.now()
    deadline = now.replace(hour=PIPELINE_WAIT_UNTIL[0], minute=PIPELINE_WAIT_UNTIL[1], second=0).timestamp()
    waited = False
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except OSError:
            if time.time() > deadline:
                f.close()
                return None
            if not waited:
                log("  毎朝のパイプラインが実行中のため、終わるのを待ちます")
                waited = True
            time.sleep(30)


def sync_running():
    """出馬表の同期（entry_fetcher.py --sync。毎朝のパイプラインのロックを取らずに動く）が実行中か"""
    for pid in os.listdir('/proc') if os.path.isdir('/proc') else []:
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                cmd = f.read().split(b'\0')
        except OSError:
            continue
        if any(c.endswith(b'entry_fetcher.py') for c in cmd) and b'--sync' in cmd:
            return True
    return False


def wait_sync(max_min=30):
    """同期が動いていれば終わるまで待つ（最大 max_min 分）。待ちきれなければ False"""
    deadline = time.time() + max_min * 60
    if sync_running():
        log("  出馬表の同期が実行中のため、終わるのを待ちます")
    while sync_running():
        if time.time() > deadline:
            return False
        time.sleep(20)
    return True


def prediction_counts(conn, race_id):
    """(出馬表の頭数, そのうち統計予想のある頭数)"""
    cur = conn.cursor()
    cur.execute("""
        SELECT (SELECT COUNT(*) FROM race_entry WHERE race_id = %s),
               (SELECT COUNT(*) FROM stats_prediction sp WHERE sp.race_id = %s
                  AND sp.horse_id IN (SELECT horse_id FROM race_entry WHERE race_id = %s))
    """, (race_id, race_id, race_id))
    heads, stats = cur.fetchone()
    cur.close()
    return heads, stats


def ensure_prediction(conn, race, expected_heads=0):
    """予想画面ができていれば True。無ければこのレースだけ作る。
    途中まで作られていても（出馬表の頭数がオッズの頭数に足りない・統計予想が一部の馬だけ）作り直す。
    expected_heads: オッズが取れた頭数（出馬表がこれより少なければ取り直す）"""
    race_id, name = race['race_id'], race['race_name']

    def entries_ok():
        heads, _ = prediction_counts(conn, race_id)
        return heads > 0 and heads >= expected_heads

    def stats_ok():
        heads, stats = prediction_counts(conn, race_id)
        return heads > 0 and stats >= heads

    if entries_ok() and stats_ok() and wp.face_analysis_done(conn, race_id):
        log("  → 予想済みのレースです（追加の取得なし）")
        return True
    lock = wait_pipeline_lock()
    if lock is not None and not wait_sync():
        lock.close()
        log("  ⛔ 出馬表の同期が終わらないため、予想作成を見送りました")
        return False
    if lock is None:
        log(f"  ⛔ 毎朝のパイプラインが {PIPELINE_WAIT_UNTIL[0]}:{PIPELINE_WAIT_UNTIL[1]:02d} までに終わらないため、"
            "予想作成を見送りました（11:20 の回でやり直します）")
        return False
    try:
        if not entries_ok():
            # entry_fetcher はそのレースの出馬表を消して入れ直す（1つのトランザクション）
            ok, _ = wp.run_script('entry_fetcher.py', ['--race-id', race_id, name, str(race['race_date'])],
                                  '出馬表・写真取得（万馬券チャレンジ）')
            if not ok or not entries_ok():
                return False
        if not stats_ok():
            # 一部の馬だけ統計予想がある（途中で失敗した）ときは、顔面データを残して全馬を計算し直す
            partial = prediction_counts(conn, race_id)[1] > 0
            ok, _ = wp.run_script('stats_predictor.py', [race_id] + (['--update'] if partial else []),
                                  '統計予想（万馬券チャレンジ）')
            if not ok or not stats_ok():
                return False
        wp.update_image_paths(conn, race_id)
        if not wp.face_analysis_done(conn, race_id):
            wp.run_script('face_analyzer_local.py', [name, race_id], '顔面分析（万馬券チャレンジ）')
        return entries_ok() and stats_ok() and wp.face_analysis_done(conn, race_id)
    finally:
        lock.close()


def describe(conn, race_id, race_name, detail, odds_list, grade):
    """選定理由と上位5頭（JSON）。馬名は出馬表（race_entry）から、無ければ馬番で書く"""
    names = horse_names(conn, race_id)
    for h in odds_list:
        if not h.get('horse_name') or h['horse_name'].endswith('番'):
            h['horse_name'] = names.get(h.get('umaban')) or (f"{h['umaban']}番" if h.get('umaban') else '—')
    reason = build_selection_reason(race_name, detail, odds_list, grade)
    top5 = json.dumps([{'umaban': h.get('umaban'), 'horse_name': h['horse_name'], 'odds': h['odds'],
                        'popularity': h['popularity']} for h in odds_list[:5]], ensure_ascii=False)
    return reason, top5


def horse_names(conn, race_id):
    cur = conn.cursor()
    cur.execute("SELECT horse_number, horse_name FROM race_entry WHERE race_id = %s AND horse_number IS NOT NULL",
                (race_id,))
    m = {n: h for n, h in cur.fetchall()}
    cur.close()
    return m


# ------------------------------------------------------------------
# メイン処理
# ------------------------------------------------------------------

def arg_value(name):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def selected_on(conn, target_date):
    cur = conn.cursor()
    cur.execute("""SELECT id, race_id, race_name, race_date, prediction_ready, venue, selection_reason, top5_json,
                          horse_count
                   FROM high_dividend_selection WHERE race_date = %s ORDER BY id DESC LIMIT 1""",
                (target_date,))
    row = cur.fetchone()
    cur.close()
    return row


def wait_odds_job(max_min=20):
    """job_runner の odds ジョブ（odds_fetcher.py）が実行中なら終わるまで待つ（最大 max_min 分）"""
    conn = get_conn()
    try:
        deadline = time.time() + max_min * 60
        first = True
        while True:
            cur = conn.cursor()
            try:
                cur.execute("""SELECT COUNT(*) FROM job_run WHERE job_name = 'odds' AND finished_at IS NULL
                               AND started_at > NOW() - INTERVAL '1 hour'""")
                running = cur.fetchone()[0] > 0
            except psycopg2.Error:
                return   # job_run が無い環境（ローカル等）
            finally:
                cur.close()
            if not running:
                return
            if time.time() > deadline:
                log(f"  ⚠️ オッズ取得が{max_min}分たっても終わらないため、DBにあるオッズで進めます")
                return
            if first:
                log("  9時のオッズ取得が実行中のため、終わるのを待ちます")
                first = False
            time.sleep(30)
    finally:
        conn.close()


def single_run():
    """選定の二重起動を防ぐ（cron と画面のボタン）。取れなければ None"""
    f = open(SELECTOR_LOCK, 'a')
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def retry_prediction(conn, row, label):
    """選定済みだが予想画面を作れなかった日: オッズは読み直さず、予想作成だけをやり直す"""
    sel_id, race_id, name, race_date, _, venue, reason, top5_json, horse_count = row
    where = f"{venue or venue_of(race_id)}{race_number_of(race_id)}R"
    log(f"{label} の万馬券チャレンジ（{where} {name}）は予想画面ができていないので、予想作成をやり直します")
    ready = ensure_prediction(conn, {'race_id': race_id, 'race_name': name, 'race_date': race_date},
                              horse_count or 0)
    # 出馬表が入ったので、馬番で書いていた上位5頭を馬名に直す
    try:
        top5 = json.loads(top5_json or '[]')
    except ValueError:
        top5 = []
    names = horse_names(conn, race_id)
    for h in top5:
        h['horse_name'] = names.get(h.get('umaban')) or h.get('horse_name')
    if top5 and reason and '。上位5頭: ' in reason:
        reason = reason.split('。上位5頭: ')[0] + '。上位5頭: ' + '、'.join(
            f"{h['horse_name']}({h['odds']}倍)" for h in top5)
    cur = conn.cursor()
    cur.execute("""UPDATE high_dividend_selection SET prediction_ready = %s, selection_reason = %s, top5_json = %s
                   WHERE id = %s""", (ready, reason, json.dumps(top5, ensure_ascii=False), sel_id))
    cur.close()
    wp.send_discord(f"💰 万馬券チャレンジ {label}（{where} {name}）: 予想画面の作成を"
                    + ("やり直して完了しました" if ready else "やり直しましたが、また失敗しました ⛔"))
    print(f'RESULT:{{"success": {str(ready).lower()}, "retried": true, "race_id": "{race_id}"}}')
    return 0 if ready else 1


def main():
    dry = '--dry-run' in sys.argv
    retry_only = '--retry-only' in sys.argv
    force = '--force' in sys.argv
    d = arg_value('--date')
    target = datetime.strptime(d, '%Y%m%d').date() if d else date.today()
    label = f"{target.month}/{target.day}"

    lock = single_run()
    if lock is None:
        log("別の万馬券チャレンジの選定が実行中のため、何もせずに終わります")
        print('RESULT:{"success": true, "skipped": "running"}')
        return 0

    conn = get_conn()
    ensure_table(conn)
    done = selected_on(conn, target)
    if retry_only:
        # 11:20 の回: 9:30 に選べた日で、予想画面を作れていないときだけ予想作成をやり直す。それ以外は何もしない
        if done and done[4] is False:
            return retry_prediction(conn, done, label)
        log(f"{label}: やり直す予想作成はありません")
        print('RESULT:{"success": true, "skipped": "nothing_to_retry"}')
        return 0
    if done and not force:
        if dry:
            log(f"{label} の万馬券チャレンジは選定済みです（{done[2]}）。試し実行でも netkeiba は読みません")
            print('RESULT:{"success": true, "dry_run": true, "skipped": "already_selected"}')
            return 0
        if done[4] is False:
            return retry_prediction(conn, done, label)
        log(f"{label} の万馬券チャレンジは選定済みです（{done[2]}）。netkeiba は読みません")
        print('RESULT:{"success": true, "skipped": "already_selected"}')
        return 0

    # 9時のオッズ取得（予想済みレースの単勝オッズを DB に入れる）がまだ動いていれば終わるのを待つ
    wait_odds_job()

    # ── 1. 候補: 予想済みのレース（DBのオッズ）＋ 予想していない特別・OP（最大 EXTRA_RACES）──
    predicted = odds_from_db(conn, target)
    if not predicted:
        # 予想しているレースが1つも無い日＝開催の無い日（祝日でない月曜など）。netkeiba は読まない
        log(f"{label} は予想しているレースが無いため、開催なしとして終わります")
        print('RESULT:{"success": true, "skipped": "no_races"}')
        return 0
    pred_ids = {r['race_id'] for r in predicted}
    got = [dict(r, source='predicted') for r in predicted if r.get('odds_list')]
    reader, stop_reason, why, extras = Reader(conn), None, {}, []
    try:
        races = fetch_race_list(reader, target)
        if races is None:
            raise Blocked('レース一覧が正常なページではありませんでした')
        if not races and not predicted:
            log(f"{label} は開催がありません")
            print('RESULT:{"success": true, "skipped": "no_races"}')
            return 0
        # 未予想の特別・OP（新馬・未勝利・N勝クラスのような名前の無いレースは除く）を頭数の多い順に。
        # 枠が余れば、予想済みなのにDBにオッズが無いレースも読む
        extras = sorted((r for r in races if r['race_id'] not in pred_ids
                         and not GENERIC_RACE_RE.search(r['race_name'])
                         and r['horse_count_hint'] >= MIN_HORSE_COUNT),
                        key=lambda r: r['horse_count_hint'], reverse=True)
        extras += [r for r in races if r['race_id'] in pred_ids
                   and not GENERIC_RACE_RE.search(r['race_name'])
                   and not any(p['race_id'] == r['race_id'] and p.get('odds_list') for p in predicted)]
        extras = extras[:EXTRA_RACES]
        if extras:
            log(f"[1] 予想していないレースから{len(extras)}レースの単勝オッズを読みます: "
                + '、'.join(f"{venue_of(r['race_id'])}{race_number_of(r['race_id'])}R {r['race_name']}" for r in extras))
            # オッズのAPIは Cookie が無いと 400 を返すので、最初にオッズのページを1回だけ開く
            reader.get(f"https://race.netkeiba.com/odds/index.html?race_id={extras[0]['race_id']}&type=b1",
                       limit_text='update limit')
            for r in extras:
                odds = fetch_win_odds(reader, r['race_id'], why)
                if odds and not enough_odds(odds, r.get('horse_count_hint')):
                    why['頭数に対してオッズが足りない'] = why.get('頭数に対してオッズが足りない', 0) + 1
                    odds = None
                r['odds_list'] = odds
    except Blocked as e:
        stop_reason = str(e)
    except requests.RequestException as e:
        stop_reason = f'通信エラー: {e}'
    if stop_reason:
        log(f"  ⚠️ {stop_reason}。ここで netkeiba の読み取りをやめます")
    got += [dict(r, source='predicted' if r['race_id'] in pred_ids else 'extra')
            for r in extras if r.get('odds_list')]
    log(f"  候補 {len(got)}レース（予想済み {len(predicted)}・追加で読めた {sum(1 for r in got if r['source'] == 'extra')}）"
        f" / netkeiba の読み取り {reader.count}回"
        + (f"（取れなかった理由: {'、'.join(f'{k} {v}件' for k, v in why.items())}）" if why else ''))

    scored = []
    for r in got:
        score, detail = calc_chaos_score(r['odds_list'], r['grade'])
        if score is None:
            continue
        r['detail'] = detail
        r['chaos_score'] = apply_generic_penalty(r['race_name'], score)
        scored.append(r)
    if not scored:
        msg = f"💰 万馬券チャレンジ {label}: 選べるレースがありませんでした" + (f"（{stop_reason}）" if stop_reason else '')
        log(msg)
        if not dry:
            wp.send_discord(msg)
        print('RESULT:{"success": false, "error": "no_candidates"}')
        return 1
    scored.sort(key=lambda r: r['chaos_score'], reverse=True)
    for r in scored[:5]:
        log(f"  {venue_of(r['race_id'])}{race_number_of(r['race_id'])}R {r['race_name']}: "
            f"1番人気 {r['detail']['favorite_odds']}倍・{r['detail']['horse_count']}頭・混戦度 {r['chaos_score']:.1f}")
    best = scored[0]
    best['venue'] = venue_of(best['race_id'])
    where = f"{best['venue']}{race_number_of(best['race_id'])}R"
    log(f"[2] 🎯 {label} の万馬券チャレンジ: {where} {best['race_name']}（混戦度 {best['chaos_score']:.1f}）")
    if dry:
        print(f'RESULT:{{"success": true, "dry_run": true, "race_id": "{best["race_id"]}"}}')
        return 0

    # ── 2. 選定を保存（予想画面ができるまでは「準備中」）。途中で落ちても行が完結しているように理由も入れる ──
    detail = best['detail']
    reason, top5 = describe(conn, best['race_id'], best['race_name'], detail, best['odds_list'], best['grade'])
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO high_dividend_selection
            (race_id, race_name, venue, race_date, horse_count, favorite_odds, odds_variance,
             chaos_score, selection_reason, top5_json, race_number, candidate_count, source, prediction_ready)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE) RETURNING id
    """, (best['race_id'], best['race_name'], best['venue'], target, detail['horse_count'],
          detail['favorite_odds'], detail['odds_variance'], best['chaos_score'], reason, top5,
          race_number_of(best['race_id']), len(scored), best['source']))
    sel_id = cur.fetchone()[0]
    cur.close()

    # ── 3. 予想画面を用意する ──
    log("[3] 予想画面を確認します")
    ready = ensure_prediction(conn, best, len(best['odds_list']))

    # 予想を作って出馬表が入ったので、馬番で書いていた馬名を直す
    reason, top5 = describe(conn, best['race_id'], best['race_name'], detail, best['odds_list'], best['grade'])
    cur = conn.cursor()
    cur.execute("""UPDATE high_dividend_selection SET selection_reason = %s, top5_json = %s, prediction_ready = %s
                   WHERE id = %s""", (reason, top5, ready, sel_id))
    cur.close()
    conn.close()

    note = f"\n⚠️ {stop_reason}" if stop_reason else ''
    wp.send_discord(f"💰 **万馬券チャレンジ {label}**: {where} {best['race_name']}（{len(scored)}レースから選定・"
                    f"混戦度 {best['chaos_score']:.1f}）\n{reason}"
                    + ('' if ready else "\n⛔ 予想画面を作れませんでした（/high-dividend には準備中と表示）") + note)
    print(f"SELECTED_RACE:{best['race_name']}")
    print(f'RESULT:{{"success": {str(ready).lower()}, "race_id": "{best["race_id"]}", '
          f'"source": "{best["source"]}", "requests": {reader.count}}}')
    return 0 if ready else 1


if __name__ == '__main__':
    sys.exit(main())
