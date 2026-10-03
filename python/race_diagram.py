"""
race_diagram.py — 鬼眼コラムの「展開の想定図」（スタート〜最初のコーナー／最後の直線）の配置を計算する

描画は画面側（Java の Thymeleaf で SVG）で行い、ここでは各馬の 前後の位置 x（0=先頭〜1=最後方）と
内外のレーン lane（0=内ラチ沿い）、そして「なぜそこに置いたか」の根拠を決める。

  図1（最初のコーナー）: 近走の序盤の平均位置（tenkai.c1）を土台に、逃げた割合・騎手の先行傾向・枠を加味
  図2（直線）    : 近走の最後のコーナーの平均位置（c4）・末脚（kick）・統計スコアの順位・想定ペース・コースの傾向

顔面分析は位置取りに一切使わない（鬼眼の印は図の上に表示するだけ）。顔面の見立てが展開の想定を
動かすと、図が「データから描いた展開」でなくなるため。

各材料の重み（W）は、過去レースの実際の通過順・着順と突き合わせる検証（tenkai_backtest.py）で決めた値。
検証の成績は python/data/tenkai_stats.json の 'model' に入っており、画面にも「この図の作り方の実績」として出す。
材料が取れない古い予想は、脚質だけから置く（従来の方法）。
"""
from __future__ import annotations

import re

import requests

import tenkai
from constants import HEADERS, decode_netkeiba

# 脚質だけ分かって平均通過順が取れないときの位置（0=先頭）
_STYLE_EARLY = {'逃げ': 0.05, '先行': 0.25, '差し': 0.55, '追込': 0.85}
_MAX_LANES = 5
_GAP = 0.07          # 同じレーンで前後の馬とこれ以上離す（重なり防止）
_shutuba_cache: dict = {}

# 材料の重み（tenkai_backtest.py の検証で決める。0 は「効果が確認できなかったので使わない」）
W = {
    'nige': 0.10,      # 図1: 逃げた割合が高いほど前へ
    'jockey': 0.0,     # 図1: 騎手の先行傾向
    'waku': 0.0,       # 図1: 外枠ほど後ろ（+）/ 前（−）
    'c4': 0.45,        # 図2: 最後のコーナーの位置
    'kick': 0.10,      # 図2: 末脚（秒）1秒あたり
    'strength': 0.45,  # 図2: 統計スコアの順位（顔面は含めない）
    'pace': 0.10,      # 図2: ハイなら前の馬が下がり、スローなら前が残る
    'course': 0.0,     # 図2: コースの先行有利・内枠有利
}


# ── 出馬表（回り・騎手） ────────────────────────────────
def shutuba_info(race_id):
    """出馬表から {'direction': '右'/'左'/'直線'/None, 'jockeys': {馬番: 騎手ID}}（レースごとに1回だけ取得）"""
    if race_id in _shutuba_cache:
        return _shutuba_cache[race_id]
    info = {'direction': None, 'jockeys': {}}
    try:
        from bs4 import BeautifulSoup
        from constants import shutuba_url
        r = requests.get(shutuba_url(race_id), headers=HEADERS, timeout=15)
        html = decode_netkeiba(r)
        m = re.search(r'\d{3,4}m\s*\((右|左|直線)', html)
        info['direction'] = m.group(1) if m else None
        for row in BeautifulSoup(html, 'lxml').find_all('tr', class_=re.compile(r'HorseList')):
            tds = row.find_all('td')
            jl = row.find('a', href=re.compile(r'/jockey/'))
            num = tds[1].get_text(strip=True) if len(tds) > 1 else ''
            mj = re.search(r'/jockey/(?:result/recent/)?(\w+)', jl['href']) if jl else None
            if num.isdigit() and mj:
                info['jockeys'][int(num)] = mj.group(1)
    except Exception:
        pass
    _shutuba_cache[race_id] = info
    return info


def course_direction(race_id):
    return shutuba_info(race_id)['direction']


def waku_of(num, field):
    """馬番と頭数から枠番を求める（JRA の規則: 8枠に均等に分け、余りは外の枠から2頭ずつ）。
    枠番が未取得のときの補完用。"""
    if not num or not field:
        return None
    if field <= 8:
        return num
    base, extra = divmod(field, 8)
    boundary = (8 - extra) * base          # 内側の枠（base 頭ずつ）に入る頭数
    if num <= boundary:
        return (num - 1) // base + 1
    return 8 - extra + (num - boundary - 1) // (base + 1) + 1


# ── 位置の計算（検証スクリプトからも使う） ────────────────────
def _pace_sign(pace):
    return {'ハイペース': 1, 'スローペース': -1}.get(pace, 0)


def early_score(h, n, w=W, stats=None):
    """図1の位置（小さいほど前）。h は num, waku, style, tenkai, jockey_id を持つ"""
    f = h.get('tenkai')
    if f and f.get('c1') is not None:
        e = f['c1'] - w['nige'] * (f.get('nige_rate') or 0)
    else:
        # 材料が無い古い予想: 脚質欄の「平均通過44%」、それも無ければ脚質から
        m = re.search(r'平均通過(\d+)%', (h.get('detail') or {}).get('脚質') or '')
        e = int(m.group(1)) / 100 if m else _STYLE_EARLY.get(h.get('style'), 0.5)
        if h.get('style') == '逃げ':
            e = min(e, 0.08)
    jb = tenkai.jockey_front(h.get('jockey_id'), stats) if w['jockey'] else None
    if jb is not None:
        e += w['jockey'] * jb
    waku = h.get('waku') or waku_of(h.get('num'), n)
    if w['waku'] and waku:
        e += w['waku'] * ((waku - 1) / 7 - 0.5)
    return e


def late_score(h, n, early, strength, pace, trend=None, w=W):
    """図2の位置（小さいほど前）。strength は統計スコアの順位で 0=最も強い〜1（顔面は含めない）"""
    f = h.get('tenkai') or {}
    c4 = f.get('c4') if f.get('c4') is not None else early
    s = w['c4'] * c4 + w['strength'] * strength
    if f.get('kick') is not None:
        s -= w['kick'] * f['kick']
    s += w['pace'] * _pace_sign(pace) * (0.5 - c4)
    if trend and w['course']:
        adv = 0.0
        if trend.get('front_top3') is not None and c4 <= 0.25:
            adv += trend['front_top3'] - trend['all_top3']
        waku = h.get('waku') or waku_of(h.get('num'), n)
        if trend.get('inner_top3') is not None and trend.get('outer_top3') is not None and waku:
            side = 1 if waku <= 3 else -1 if waku >= 6 else 0
            adv += side * (trend['inner_top3'] - trend['outer_top3']) / 2
        s -= w['course'] * adv / max(0.05, trend['all_top3'])
    return s


def strengths(horses):
    """統計スコア（近走成績・距離・馬場・調教など。顔面分析は含まない）の順位 → 0（最も強い）〜1"""
    n = len(horses)
    ranked = sorted(horses, key=lambda h: (h.get('stats_score') is None, -(h.get('stats_score') or 0), h['num']))
    return {h['num']: i / max(1, n - 1) for i, h in enumerate(ranked)}


# ── 配置 ─────────────────────────────────────────────
def _assign_lanes(ordered, pref):
    """前から順に、希望レーンに近い空きレーンへ置く（同じレーンで前の馬と _GAP 以上離れていること）"""
    last_x = {}
    out = []
    for h, x in ordered:
        want = pref(h)
        for lane in sorted(range(_MAX_LANES), key=lambda l: (abs(l - want), l)):
            if lane not in last_x or x - last_x[lane] >= _GAP:
                break
        else:
            lane = min(range(_MAX_LANES), key=lambda l: last_x.get(l, -1))
            x = last_x[lane] + _GAP
        last_x[lane] = x
        out.append((h, min(x, 1.0), lane))
    return out


def _spread(values):
    """順位による等間隔と値そのものを半々で混ぜ、0〜1 に並べる（固まり具合を残しつつ重なりにくく）"""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    lo, hi = min(values), max(values)
    out = [0.0] * n
    for rank, i in enumerate(order):
        even = rank / (n - 1) if n > 1 else 0.0
        norm = (values[i] - lo) / (hi - lo) if hi > lo else even
        out[i] = 0.5 * even + 0.5 * norm
    return out


# ── 根拠の文章 ─────────────────────────────────────────
def _pos(r, n):
    return f"{tenkai.to_position(r, n):.1f}番手"


def _why_early(h, n, stats):
    f = h.get('tenkai')
    if not f or f.get('c1') is None:
        return f"脚質（{h.get('style') or '不明'}）から想定"
    parts = [f"近{f['n']}走の序盤（最初に記録されたコーナー）平均{_pos(f['c1'], n)}相当"]
    if f.get('nige_rate'):
        parts.append(f"ハナを切った割合 {f['nige_rate']:.0%}")
    jb = tenkai.jockey_front(h.get('jockey_id'), stats) if W['jockey'] else None
    if jb is not None and abs(jb) >= 0.03:
        parts.append('騎手は' + ('前へ行かせる' if jb < 0 else '控える') + '傾向')
    return '・'.join(parts)


def _why_late(h, n, kick_rank):
    f = h.get('tenkai')
    if not f or f.get('c4') is None:
        return '脚質と統計スコアの順位から想定'
    parts = [f"最後のコーナー 平均{_pos(f['c4'], n)}相当"]
    if h['num'] in kick_rank:
        parts.append(f"上がり（各レースの後半3F比）はメンバー中{kick_rank[h['num']]}位")
    if f.get('gain') is not None and abs(f['gain']) >= 0.05:
        g = f['gain'] * n
        parts.append(f"最後のコーナーからゴールまで平均{abs(g):.1f}頭{'抜く' if g > 0 else '抜かれる'}")
    return '・'.join(parts)


def pace_forecast(horses, stats=None):
    """想定ペースの根拠と、検証での的中率。ペースを決めたのと同じ基準で根拠の馬を選ぶ
    （新しい基準＝逃げ候補の頭数 / 従来＝脚質「逃げ」「先行」の頭数）"""
    stats = stats or tenkai.load_stats()
    model = stats.get('model') or {}
    rule = tenkai.pace_rule(stats)
    if rule:
        _, idx = tenkai.pace_by_leaders([h.get('tenkai') for h in horses], rule)
        basis, nums = '近走でハナを切る・序盤をごく前で運ぶことが多い馬', [horses[i]['num'] for i in idx]
    else:
        basis = '脚質が逃げの馬'
        nums = [h['num'] for h in horses if h.get('style') == '逃げ']
    return {'leaders': sorted(nums), 'basis': basis, 'accuracy': model.get('pace_accuracy')}


# ── 本体 ─────────────────────────────────────────────
def build(horses, pace, direction, course_key=None, abroad=False):
    """horses: column_writer の馬リスト（num, waku, style, detail, stats_score, mark, name, tenkai, jockey_id）。
    mark（鬼眼の印）は表示用で、位置の計算には使わない。
    戻り値は画面に渡す辞書（JSON にして race_column.diagram へ保存する）"""
    n = len(horses)
    if n < 2:
        return None
    # 位置取りの材料（近走の通過順・脚質）がほとんど無いレース（海外など）は、図を描いても根拠が無いので描かない
    if sum(1 for h in horses if h.get('tenkai') or h.get('style')) < n / 2:
        return None
    stats = tenkai.load_stats()
    trend = tenkai.course_trend(course_key, stats) if course_key else None

    # ── 図1: スタート〜最初のコーナー ─────────────────────────
    early = [early_score(h, n, W, stats) for h in horses]
    xs1 = _spread(early)
    ordered1 = sorted(zip(horses, xs1), key=lambda t: (t[1], t[0]['num']))
    # 内外は枠の並びを基本に（外枠ほど外）。逃げ・先行馬はなるべく内へ切れ込む
    def pref1(h):
        base = round((h['num'] - 1) / max(1, n - 1) * 3)
        return max(0, base - 1) if h['style'] in ('逃げ', '先行') else base
    scene1 = _assign_lanes(ordered1, pref1)

    # ── 図2: 最後の直線 ──────────────────────────────
    strength = strengths(horses)
    late = [late_score(h, n, early[i], strength[h['num']], pace, trend) for i, h in enumerate(horses)]
    xs2 = _spread(late)
    ordered2 = sorted(zip(horses, xs2), key=lambda t: (t[1], t[0]['num']))
    # 直線では差し・追込は外へ持ち出し、先行勢は内で粘る
    def pref2(h):
        return {'逃げ': 0, '先行': 1, '差し': 3, '追込': 4}.get(h['style'], 2)
    scene2 = _assign_lanes(ordered2, pref2)

    def pack(scene, why):
        # 海外のレースには JRA の枠が無いので、枠の色を補わない（丸は灰色）
        return [{'num': h['num'], 'waku': h['waku'] or (None if abroad else waku_of(h['num'], n)),
                 'mark': h['mark'], 'style': h['style'],
                 'name': h['name'], 'x': round(x, 3), 'lane': lane, 'why': why(h)} for h, x, lane in scene]

    # 末脚の順位（近走の上がり3F が、そのレースの後半3F より何秒速かったかの平均で比べる）
    kicks = sorted((h for h in horses if (h.get('tenkai') or {}).get('kick') is not None),
                   key=lambda h: -h['tenkai']['kick'])
    kick_rank = {h['num']: i + 1 for i, h in enumerate(kicks)}

    straight = direction == '直線'
    model = stats.get('model') or {}
    course_note = None
    if trend and trend.get('front_top3') is not None:
        course_note = (f"{course_key}は序盤に前（前から4分の1以内）にいた馬の3着内率 {trend['front_top3']:.0%}"
                       f"（全体 {trend['all_top3']:.0%}）")
        if trend.get('inner_top3') is not None and trend.get('outer_top3') is not None:
            course_note += f"・内枠(1-3) {trend['inner_top3']:.0%} / 外枠(6-8) {trend['outer_top3']:.0%}"
    return {
        'direction': direction or '右',
        'pace': pace,
        'evidence': {
            'pace': dict(pace_forecast(horses, stats), label=pace),
            'course': course_note,
            'model': {k: model.get(k) for k in ('races', 'kind', 'start_top4', 'stretch_top4', 'start_corr', 'finish_corr',
                                                'base_start_top4', 'base_stretch_top4', 'pace_total')
                      if model.get(k) is not None},
            'with_data': sum(1 for h in horses if h.get('tenkai')),
        },
        'scenes': [
            {'key': 'start', 'title': 'スタート直後の隊列（想定）' if straight else 'スタート〜最初のコーナー（想定）',
             'goal': '進行方向' if straight else '最初のコーナーへ',
             'horses': pack(scene1, lambda h: _why_early(h, n, stats))},
            {'key': 'stretch', 'title': 'ゴール前（想定）' if straight else '最後の直線（想定）',
             'goal': 'ゴール', 'horses': pack(scene2, lambda h: _why_late(h, n, kick_rank))},
        ],
    }


def summary(diagram, scene_key, top=4):
    """図の先頭から数頭を「10番ウェイワードアクト」の形で（コラム本文の材料用）"""
    for s in (diagram or {}).get('scenes', []):
        if s['key'] == scene_key:
            return [f"{h['num']}番{h['name']}" for h in s['horses'][:top]]
    return []


def evidence_lines(diagram, top=4):
    """コラム本文の材料用: 図の先頭数頭の根拠（「10番ウェイワードアクト: 近6走の…」）"""
    out = {}
    for s in (diagram or {}).get('scenes', []):
        out[s['key']] = [f"{h['num']}番{h['name']}: {h.get('why')}" for h in s['horses'][:top] if h.get('why')]
    return out
