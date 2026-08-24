"""race_condition.py — レース当日の馬場状態を確定 / 前日天気から予測する

優先順位:
  1. netkeibaのレースページに馬場が出ていればそれを採用（当日〜開催後は確定値）
  2. 出ていなければ気象庁の予報から推定（前日の天気 + 当日の予報）
  3. どちらも失敗 → None（呼び出し側は「良」相当の中立として扱う）

※ 推定はヒューリスティックであり確定値ではない。実際の馬場は降水量だけでなく
   含水率・馬場造園作業・開催週の進行度でも変わる。予想では弱めに効かせること。

気象庁の予報API（認証不要・無料）:
  https://www.jma.go.jp/bosai/forecast/data/forecast/{area_code}.json
"""
import re
import json
from datetime import date, timedelta

import requests

from constants import HEADERS, decode_netkeiba

# ── netkeiba の場コード（race_id の 5〜6文字目）──────────────
PLACE_BY_CODE = {
    '01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
    '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉',
}

# ── 競馬場 → 気象庁の府県予報区コード ────────────────────────
JMA_AREA = {
    '札幌': '016000',  # 石狩・空知・後志
    '函館': '017000',  # 渡島・檜山
    '福島': '070000',
    '新潟': '150000',
    '東京': '130000',  # 府中
    '中山': '120000',  # 千葉県（船橋）
    '中京': '230000',  # 愛知県
    '京都': '260000',
    '阪神': '280000',  # 兵庫県（宝塚）
    '小倉': '400000',  # 福岡県
}

CONDITIONS = ('良', '稍重', '重', '不良')

# 降水確率 → 湿り度スコア
_POP_WETNESS = ((80, 3.0), (60, 2.2), (50, 1.6), (30, 0.8), (20, 0.3))
# 天気コード先頭桁 → 加点（1:晴 2:曇 3:雨 4:雪）
_CODE_WETNESS = {'1': 0.0, '2': 0.2, '3': 1.5, '4': 1.5}
# 前日の雨は一部乾くため割り引く
_PREV_DAY_WEIGHT = 0.6
# 合計スコア → 馬場（大きいほど悪化）
# ※ 実測との突き合わせで較正した値。過敏に「稍重」を出さないようにしてある。
_THRESHOLDS = ((5.5, '不良'), (3.2, '重'), (1.6, '稍重'))
# 降水確率がこの値未満なら、天気テキストに「雨」があっても軽微扱いにする上限
_LOW_POP_CAP = (30, 0.5)


def place_from_race_id(race_id):
    """race_id（例 202602011010）から競馬場名を返す。不明なら None。"""
    if not race_id or len(str(race_id)) < 6:
        return None
    return PLACE_BY_CODE.get(str(race_id)[4:6])


def _normalize_condition(raw):
    """netkeiba表記（良/稍/重/不）を正式名称に揃える。"""
    if not raw:
        return None
    raw = raw.strip()
    table = {'良': '良', '稍': '稍重', '稍重': '稍重',
             '重': '重', '不': '不良', '不良': '不良'}
    return table.get(raw)


# ----------------------------------------------------------------
# 1. netkeiba から確定値を取る
# ----------------------------------------------------------------
def fetch_actual_condition(race_id, session=None):
    """レースページの「馬場:○」を取得。返り値 (馬場, 天候) / 取れなければ (None, None)。

    出馬表ページは開催当日にならないと馬場を出さないため、前日以前は (None, None)。
    """
    if not race_id:
        return None, None
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    try:
        s = session or requests.Session()
        s.headers.update(HEADERS)
        r = s.get(url, timeout=15)
        text = decode_netkeiba(r)
        m_baba = re.search(r'馬場\s*[:：]\s*(良|稍重|稍|重|不良|不)', text)
        m_tenki = re.search(r'天候\s*[:：]\s*(晴|曇|小雨|雨|小雪|雪)', text)
        return (_normalize_condition(m_baba.group(1)) if m_baba else None,
                m_tenki.group(1) if m_tenki else None)
    except Exception as e:
        print(f"  [警告] 馬場の取得失敗: {e}")
        return None, None


# ----------------------------------------------------------------
# 2. 気象庁の予報から推定する
# ----------------------------------------------------------------
def _jma_daily(area_code):
    """{'YYYY-MM-DD': {'code':str,'pop':int,'text':str}} を返す。

    3日予報（詳細・テキスト付き）を優先し、足りない日を週間予報で補う。
    """
    url = f"https://www.jma.go.jp/bosai/forecast/data/forecast/{area_code}.json"
    r = requests.get(url, headers={'User-Agent': HEADERS['User-Agent']}, timeout=15)
    r.raise_for_status()
    data = json.loads(r.content.decode('utf-8'))
    out = {}

    def day_of(iso):
        return iso[:10]

    # ── 週間予報（先に入れて、後から3日予報で上書きする）──
    if len(data) > 1:
        for ts in data[1].get('timeSeries', []):
            a = ts['areas'][0]
            if 'weatherCodes' not in a:
                continue
            for i, t in enumerate(ts['timeDefines']):
                pop = a.get('pops', [])
                out[day_of(t)] = {
                    'code': (a['weatherCodes'][i] or '')[:3],
                    'pop':  int(pop[i]) if i < len(pop) and str(pop[i]).isdigit() else None,
                    'text': '',
                }

    # ── 3日予報（天気テキストあり・こちらが正確）──
    series = data[0].get('timeSeries', [])
    if series:
        a = series[0]['areas'][0]
        for i, t in enumerate(series[0]['timeDefines']):
            d = day_of(t)
            cur = out.get(d, {})
            cur['code'] = (a['weatherCodes'][i] or '')[:3]
            cur['text'] = a.get('weathers', [''] * (i + 1))[i].replace('　', '')
            out[d] = cur
    # 降水確率は6時間ごと → 日単位の最大値を採用
    if len(series) > 1 and 'pops' in series[1]['areas'][0]:
        a = series[1]['areas'][0]
        per_day = {}
        for i, t in enumerate(series[1]['timeDefines']):
            v = a['pops'][i]
            if str(v).isdigit():
                per_day.setdefault(day_of(t), []).append(int(v))
        for d, vals in per_day.items():
            out.setdefault(d, {'code': '', 'text': ''})
            out[d]['pop'] = max(vals)
    return out


def _wetness(day):
    """1日分の天気情報 → 湿り度スコア。"""
    if not day:
        return 0.0, '情報なし'
    pt = 0.0
    pop = day.get('pop')
    if pop is not None:
        for th, v in _POP_WETNESS:
            if pop >= th:
                pt += v
                break
    code = (day.get('code') or '')[:1]
    pt += _CODE_WETNESS.get(code, 0.0)
    # テキストに雨/雪が明示されていれば加点（コードだけでは拾えない「時々雨」対策）。
    # ただし「所により」「にわか」は局地的・一時的なので軽く見る。
    text = day.get('text') or ''
    if '雨' in text or '雪' in text:
        pt += 0.2 if ('所により' in text or 'にわか' in text) else 0.6
    # 降水確率が低い日は、文言に雨があっても馬場を悪化させるほど降らない。
    # （「晴れ／所により雨／降水20%」で稍重と誤判定していた問題への対策）
    low_th, cap = _LOW_POP_CAP
    if pop is not None and pop < low_th:
        pt = min(pt, cap)
    label = text or {'1': '晴', '2': '曇', '3': '雨', '4': '雪'}.get(code, '?')
    desc = f"{label}" + (f"/降水{pop}%" if pop is not None else "")
    return pt, desc


def estimate_condition(place, race_date):
    """前日+当日の予報から馬場を推定。返り値 dict（失敗時 None）。"""
    area = JMA_AREA.get(place)
    if not area or not race_date:
        return None
    try:
        daily = _jma_daily(area)
    except Exception as e:
        print(f"  [警告] 気象庁予報の取得失敗({place}): {e}")
        return None

    if isinstance(race_date, str):
        race_date = date.fromisoformat(race_date[:10])
    d_race = race_date.isoformat()
    d_prev = (race_date - timedelta(days=1)).isoformat()

    if d_race not in daily and d_prev not in daily:
        return None  # 予報範囲外（1週間以上先など）

    w_prev, s_prev = _wetness(daily.get(d_prev))
    w_race, s_race = _wetness(daily.get(d_race))
    total = w_prev * _PREV_DAY_WEIGHT + w_race

    cond = '良'
    for th, name in _THRESHOLDS:
        if total >= th:
            cond = name
            break

    return {
        'condition':  cond,
        'source':     '気象庁予報',
        'confidence': 'low' if d_race not in daily else 'medium',
        'score':      round(total, 2),
        'reason':     f"前日({s_prev}) + 当日({s_race}) → 湿り度{total:.1f} → {cond}",
    }


# ----------------------------------------------------------------
# 3. 呼び出し口
# ----------------------------------------------------------------
def resolve_condition(race_id, race_date, place=None):
    """馬場を確定 or 推定して dict で返す。必ず dict（不明時は condition=None）。"""
    place = place or place_from_race_id(race_id)

    actual, tenki = fetch_actual_condition(race_id)
    if actual:
        return {'condition': actual, 'source': 'netkeiba確定', 'confidence': 'high',
                'reason': f"レースページの馬場表記より（天候:{tenki or '?'}）", 'weather': tenki}

    est = estimate_condition(place, race_date)
    if est:
        est['weather'] = None
        return est

    return {'condition': None, 'source': 'なし', 'confidence': 'none',
            'reason': '馬場を特定できず（中立扱い）', 'weather': None}


if __name__ == '__main__':
    import sys
    rid = sys.argv[1] if len(sys.argv) > 1 else '202602011010'
    d   = sys.argv[2] if len(sys.argv) > 2 else date.today().isoformat()
    print(f"race_id={rid} / 場={place_from_race_id(rid)} / 日付={d}")
    print(json.dumps(resolve_condition(rid, d), ensure_ascii=False, indent=2))
