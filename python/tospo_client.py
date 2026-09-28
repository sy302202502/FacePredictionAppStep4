"""
tospo_client.py — 東スポ競馬（有料会員）から予想の補正材料を取る

【使うデータ】
  1. 東スポ指数（/race/detail/<race_id>/rating）
       過去1年ベスト・当該距離ベスト・ベスト の指数（スピード指数）
  2. 記者の印（/race/detail/<race_id>/card の raceForecast.reporterMarks）
       ◎○▲△ の集計（公開は土曜レース=金曜18時 / 日曜レース=土曜15時）
  race_id は netkeiba と同じ12桁、馬は studbookCode（= netkeiba の horse_id）で突合する。

【規約上の扱い（重要）】
  東スポ競馬の利用規約は、コンテンツの転載・二次利用と商業的利用を禁じている。
  このアプリでは生データ（指数・印・記者名）を画面・DB・ログに出さず、
  統計スコアの「専門紙補正」（数値のみ）としてだけ使う。
  .env の TOSPO_ENABLED=1 のときだけ動く。0 にすれば即座に無効化できる。

【.env】
  TOSPO_ENABLED=1
  TOSPO_LOGIN_EMAIL=<会員のメールアドレス>
  TOSPO_PASSWORD=<パスワード>
  （未設定でも指数は公開範囲で取れる。印は会員ログインが必要）
"""
from __future__ import annotations

import os
import pickle
import re

import requests
from dotenv import load_dotenv

from constants import HEADERS

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

BASE = 'https://tospo-keiba.jp'
_COOKIE_FILE = os.path.join(os.path.dirname(__file__), '../.tospo_cookies.pkl')
_XHR = {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}

# 記者印の種類 → 重み。2=◎ 3=○ 4=▲、5・6 は△系（各記者とも2〜4は1頭ずつ、5・6は複数頭）
MARK_WEIGHT = {2: 5.0, 3: 3.0, 4: 2.0, 5: 1.0, 6: 1.0}

# 補正の幅（pt）。統計スコア100点に対して控えめにする
INDEX_RANGE = 3.0   # 指数: レース内の最低 -3.0 〜 最高 +3.0
MARKS_MAX   = 4.0   # 記者印: 最も支持された馬に +4.0


def enabled():
    return os.getenv('TOSPO_ENABLED', '0').strip() == '1'


def _session():
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        if os.path.exists(_COOKIE_FILE):
            with open(_COOKIE_FILE, 'rb') as f:
                s.cookies.update(pickle.load(f))
    except Exception:
        pass
    return s


def _login(s):
    """会員ログイン（Laravel のフォーム: _token / email / password）。成功で True。"""
    email = os.getenv('TOSPO_LOGIN_EMAIL', '').strip()
    password = os.getenv('TOSPO_PASSWORD', '').strip()
    if not email or not password:
        return False
    try:
        r = s.get(f'{BASE}/login', timeout=15)
        m = re.search(r'name="_token"\s+value="([^"]+)"', r.text)
        if not m:
            print("  [東スポ] ログインフォームを解析できません")
            return False
        s.post(f'{BASE}/login', data={'_token': m.group(1), 'email': email, 'password': password,
                                      'callBackUrl': ''}, timeout=15)
        with open(_COOKIE_FILE, 'wb') as f:
            pickle.dump(s.cookies, f)
        return True
    except Exception as e:
        print(f"  [東スポ] ログイン例外: {e}")
        return False


def _get_json(s, race_id, page):
    r = s.get(f'{BASE}/race/detail/{race_id}/{page}', headers=_XHR, timeout=15)
    if r.status_code != 200 or 'json' not in (r.headers.get('content-type') or ''):
        return None
    return (r.json() or {}).get('body')


def _rating_value(h):
    """1頭の指数: 過去1年ベストと当該距離ベストの高い方（近走の能力×今回の距離）。
    どちらも無ければ生涯ベスト。無ければ None。"""
    vals = [(h.get(k) or {}).get('rating') for k in ('yearlyBestRating', 'bestLengthRating')]
    vals = [v for v in vals if isinstance(v, (int, float))]
    if vals:
        return max(vals)
    best = (h.get('bestRating') or {}).get('rating')
    return best if isinstance(best, (int, float)) else None


def fetch_adjustments(race_id):
    """{horse_id: 補正pt} を返す。無効・取得失敗は {}（＝補正なし）。
    生データは返さない（保存・表示させないため）。"""
    if not enabled() or not race_id:
        return {}
    try:
        s = _session()
        rating = _get_json(s, race_id, 'rating')
        if rating is not None and not rating.get('isLogin') and os.getenv('TOSPO_LOGIN_EMAIL'):
            if _login(s):
                rating = _get_json(s, race_id, 'rating') or rating
        card = _get_json(s, race_id, 'card')
    except Exception as e:
        print(f"  [東スポ] 取得失敗: {e}")
        return {}

    adj = {}

    # ── 指数: レース内の相対位置で -INDEX_RANGE〜+INDEX_RANGE ──
    idx = {}
    id_by_entry = {}
    for h in (rating or {}).get('raceRatingList') or []:
        if h.get('withdrawn'):
            continue
        v = _rating_value(h)
        entry = next((e for e in (rating.get('raceEntryList') or [])
                      if e.get('raceEntryId') == h.get('raceEntryId')), {})
        hid = entry.get('studbookCode')
        if hid:
            id_by_entry[h.get('raceEntryId')] = hid
            if v is not None:
                idx[hid] = v
    if len(idx) >= 3:
        lo, hi = min(idx.values()), max(idx.values())
        for hid, v in idx.items():
            adj[hid] = 0.0 if hi == lo else (v - lo) / (hi - lo) * 2 * INDEX_RANGE - INDEX_RANGE

    # ── 記者印: 印の重みの合計をレース最大で割って 0〜MARKS_MAX ──
    for e in (card or {}).get('raceEntryList') or []:
        if e.get('studbookCode'):
            id_by_entry.setdefault(e.get('raceEntryId'), e['studbookCode'])
    marks = (((card or {}).get('raceForecast') or {}).get('reporterMarks')) or {}
    support = {}
    for per_reporter in marks.values():
        for m in (per_reporter or {}).values():
            hid = id_by_entry.get(m.get('raceEntryId'))
            w = MARK_WEIGHT.get(m.get('reporterMarkType'), 0.0)
            if hid and w:
                support[hid] = support.get(hid, 0.0) + w
    if support:
        top = max(support.values())
        for hid, v in support.items():
            adj[hid] = adj.get(hid, 0.0) + v / top * MARKS_MAX

    return {hid: round(v, 1) for hid, v in adj.items()}


if __name__ == '__main__':
    import sys
    rid = sys.argv[1] if len(sys.argv) > 1 else ''
    if not enabled():
        print("TOSPO_ENABLED=1 ではないため無効です")
        sys.exit(0)
    res = fetch_adjustments(rid)
    print(f"{len(res)}頭分の補正を取得（値は表示しません）")
    sys.exit(0 if res else 1)
