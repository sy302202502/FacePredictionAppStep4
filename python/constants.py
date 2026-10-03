"""共通定数・ユーティリティモジュール"""

import time
import random
import requests

# 全スクリプト共通のリクエストヘッダー
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}


def polite_sleep(min_sec=1.0, max_sec=2.5):
    """BAN対策: ランダムな待機時間を挿入する"""
    time.sleep(random.uniform(min_sec, max_sec))


def decode_netkeiba(resp):
    """netkeibaのレスポンスを正しい文字コードでデコードして本文(str)を返す。
    netkeibaはドメイン/ページごとに UTF-8 と EUC-JP が混在し、随時移行されるため、
    HTTPヘッダ → meta charset → chardet自動判定 の順で確実なエンコーディングを選ぶ。
    （ハードコードのEUC-JP固定が原因で UTF-8 移行後に馬名が文字化けした不具合への恒久対策）"""
    import re as _re
    enc = None
    # 1. HTTPヘッダの charset（requestsが既にセットしていれば優先。ただしデフォルトのISO-8859-1は無視）
    ct = resp.headers.get('Content-Type', '')
    m = _re.search(r'charset=([\w-]+)', ct, _re.I)
    if m:
        enc = m.group(1)
    # 2. HTMLの meta charset
    if not enc:
        m = _re.search(rb'charset=["\']?([\w-]+)', resp.content[:3000], _re.I)
        if m:
            enc = m.group(1).decode('ascii', 'ignore')
    # 3. それでも不明なら chardet 自動判定
    if not enc:
        enc = resp.apparent_encoding or 'utf-8'
    resp.encoding = enc
    return resp.text


def is_garbled(text):
    """文字化けを検知する。Trueなら化けている可能性が高い。
    馬名・レース名の保存前チェック用。化けた文字（置換文字・私用領域・
    ラテン拡張の連続）が日本語テキストに混入していないかを見る。"""
    if not text:
        return False
    # 置換文字（デコード失敗の証拠）
    if '�' in text or '�' == text or '\x00' in text:
        return True
    bad = 0
    for c in text:
        o = ord(c)
        # 私用領域（EUC-JP→UTF-8誤変換でよく出る）
        if 0xE000 <= o <= 0xF8FF:
            bad += 1
        # ラテン1補助・拡張（日本語名に本来出ない範囲）
        elif 0x0080 <= o <= 0x024F:
            bad += 1
    # 2文字以上の不正文字、または全体の3割超が不正なら化け判定
    return bad >= 2 or (bad > 0 and bad / len(text) > 0.3)


# コネクション再利用のための共有セッション（TLSハンドシェイク削減・netkeibaへの負荷軽減）
_session = requests.Session()
_session.headers.update(HEADERS)


def fetch_with_retry(url, headers=None, timeout=15, retries=3, min_sleep=1.0, max_sleep=2.5):
    """リトライ付きHTTP GETリクエスト。
    - 共有Sessionでコネクション再利用
    - 429 は Retry-After ヘッダを尊重して待機
    - 429以外の4xx（404等）はリトライしても結果が変わらないため即時失敗
    - 5xx・ネットワークエラーは指数バックオフで再試行"""
    last_exc = None
    for attempt in range(retries):
        try:
            resp = _session.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            polite_sleep(min_sleep, max_sleep)
            return resp
        except requests.HTTPError as e:
            last_exc = e
            status = e.response.status_code if e.response is not None else 0
            if status == 429:
                # サーバ指示の待機時間を尊重（無ければバックオフ。上限120秒）
                ra = e.response.headers.get('Retry-After', '')
                wait = min(float(ra), 120.0) if ra.isdigit() else random.uniform(5.0, 10.0) * (attempt + 1)
                print(f"  [429リトライ {attempt + 1}/{retries}] {wait:.0f}秒待機", flush=True)
                time.sleep(wait)
                continue
            if 400 <= status < 500:
                raise  # 4xxは再試行無意味（URL誤り・削除済みページ等）
            if attempt < retries - 1:
                wait = random.uniform(3.0, 6.0) * (attempt + 1)
                print(f"  [リトライ {attempt + 1}/{retries}] {wait:.1f}秒後に再試行: {e}", flush=True)
                time.sleep(wait)
        except Exception as e:
            last_exc = e
            if attempt < retries - 1:
                wait = random.uniform(3.0, 6.0) * (attempt + 1)
                print(f"  [リトライ {attempt + 1}/{retries}] {wait:.1f}秒後に再試行: {e}", flush=True)
                time.sleep(wait)
    raise last_exc


# ----------------------------------------------------------------
# コース表記（出馬表の RaceData01）の解析
# ----------------------------------------------------------------
# netkeiba の表記は「芝2000m」「ダ1700m」「障4260m (芝 外)」など。
# 旧実装は「ダート1700m」しか想定しておらず、ダート戦がすべて
# 「芝・距離不明（→2000m扱い）」で保存・採点されていた。
_COURSE_RE = None


def parse_course(text):
    """RaceData01 のテキストから (surface, distance) を返す。
    surface は '芝' / 'ダート' / '障害'。読めなければ (None, None)。"""
    import re as _re
    global _COURSE_RE
    if not text:
        return None, None
    if _COURSE_RE is None:
        # 「障」「芝」「ダ」「ダート」の直後に距離が続く箇所だけを拾う（賞金等の数字を誤認しない）
        # 結果ページは「芝右2000m」「ダ右1700m」「障芝 外4260m」のように回りや内外が挟まる
        _COURSE_RE = _re.compile(r'(障)?\s*(芝|ダート|ダ)?[右左外内直線\s]*(?:\d周)?[右左外内\s]*(\d{3,4})\s*m')
    m = next((x for x in _COURSE_RE.finditer(text) if x.group(1) or x.group(2)), None)
    if not m:
        return None, None
    if m.group(1):
        surface = '障害'
    elif m.group(2) in ('ダ', 'ダート'):
        surface = 'ダート'
    else:
        surface = '芝'
    return surface, int(m.group(3))


def is_race_id(s):
    """netkeiba の race_id か（中央は12桁の数字、海外は「2026C8010105」のように英字が入る）"""
    import re as _re
    return bool(s) and bool(_re.fullmatch(r'\d{4}[0-9A-Z]{8}', str(s)))


def is_abroad(race_id):
    """海外のレース（race_id に英字が入る）か。出馬表は shutuba_abroad.html、JRA の枠は無い"""
    return bool(race_id) and not str(race_id).isdigit()


def shutuba_url(race_id):
    page = 'shutuba_abroad' if is_abroad(race_id) else 'shutuba'
    return f"https://race.netkeiba.com/race/{page}.html?race_id={race_id}"


def surface_of_distance_cell(cell):
    """馬の成績表「距離」列（例: 芝2000 / ダ1800 / 障3000）→ '芝' / 'ダート' / '障害'。"""
    cell = (cell or '').strip()
    if cell.startswith('障'):
        return '障害'
    if cell.startswith('ダ'):
        return 'ダート'
    return '芝'
