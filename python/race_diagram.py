"""
race_diagram.py — 鬼眼コラムの「展開の想定図」（スタート〜1コーナー／最後の直線）の配置を計算する

描画は画面側（Java の Thymeleaf で SVG）で行い、ここでは各馬の 前後の位置 x（0=先頭〜1=最後方）と
内外のレーン lane（0=内ラチ沿い）だけを決める。材料はコラム本文と同じ（脚質・近走の平均通過順・
想定ペース・鬼眼の順位）なので、図と文章が食い違わない。あくまで「想定」の図であり、実際の展開は
出遅れや騎手の判断で変わる（画面にもその旨を表示する）。
"""
from __future__ import annotations

import re

import requests

from constants import HEADERS, decode_netkeiba

# 脚質だけ分かって平均通過順が取れないときの位置（0=先頭）
_STYLE_EARLY = {'逃げ': 0.05, '先行': 0.25, '差し': 0.55, '追込': 0.85}
_MAX_LANES = 5
_GAP = 0.07          # 同じレーンで前後の馬とこれ以上離す（重なり防止）
_direction_cache: dict = {}


def course_direction(race_id):
    """出馬表の「芝1800m (左)」などから 回り を返す: '右' / '左' / '直線' / None"""
    if race_id in _direction_cache:
        return _direction_cache[race_id]
    d = None
    try:
        r = requests.get(f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}",
                         headers=HEADERS, timeout=15)
        m = re.search(r'\d{3,4}m\s*\((右|左|直線)', decode_netkeiba(r))
        d = m.group(1) if m else None
    except Exception:
        pass
    _direction_cache[race_id] = d
    return d


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


def _early(h):
    """序盤の位置（0=先頭〜1=最後方）。近走の平均通過順（例「平均通過44%」）を優先し、無ければ脚質から"""
    m = re.search(r'平均通過(\d+)%', h['detail'].get('脚質') or '')
    e = int(m.group(1)) / 100 if m else _STYLE_EARLY.get(h['style'], 0.5)
    if h['style'] == '逃げ':
        e = min(e, 0.08)
    return e


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


def build(horses, pace, direction):
    """horses: column_writer の馬リスト（num, waku, style, detail, composite, mark を持つ）。
    戻り値は画面に渡す辞書（JSON にして race_column.diagram へ保存する）"""
    n = len(horses)
    if n < 2:
        return None
    early = [_early(h) for h in horses]

    # ── 図1: スタート〜1コーナー ─────────────────────────
    xs1 = _spread(early)
    ordered1 = sorted(zip(horses, xs1), key=lambda t: (t[1], t[0]['num']))
    # 内外は枠の並びを基本に（外枠ほど外）。逃げ・先行馬はなるべく内へ切れ込む
    def pref1(h):
        base = round((h['num'] - 1) / max(1, n - 1) * 3)
        return max(0, base - 1) if h['style'] in ('逃げ', '先行') else base
    scene1 = _assign_lanes(ordered1, pref1)

    # ── 図2: 最後の直線 ──────────────────────────────
    ranked = sorted(horses, key=lambda h: (h['composite'] is None, -(h['composite'] or 0), h['num']))
    strength = {h['num']: i / max(1, n - 1) for i, h in enumerate(ranked)}  # 0=最も強い
    w_pos = {'ハイペース': 0.35, 'スローペース': 0.65}.get(pace, 0.5)
    closer_bonus = {'ハイペース': -0.12, 'スローペース': 0.08}.get(pace, 0.0)
    late = [w_pos * early[i] + (1 - w_pos) * strength[h['num']]
            + (closer_bonus if h['style'] in ('差し', '追込') else 0.0)
            for i, h in enumerate(horses)]
    xs2 = _spread(late)
    ordered2 = sorted(zip(horses, xs2), key=lambda t: (t[1], t[0]['num']))
    # 直線では差し・追込は外へ持ち出し、先行勢は内で粘る
    def pref2(h):
        return {'逃げ': 0, '先行': 1, '差し': 3, '追込': 4}.get(h['style'], 2)
    scene2 = _assign_lanes(ordered2, pref2)

    def pack(scene):
        return [{'num': h['num'], 'waku': h['waku'] or waku_of(h['num'], n), 'mark': h['mark'], 'style': h['style'],
                 'name': h['name'], 'x': round(x, 3), 'lane': lane} for h, x, lane in scene]

    straight = direction == '直線'
    return {
        'direction': direction or '右',
        'pace': pace,
        'scenes': [
            {'key': 'start', 'title': 'スタート直後の隊列（想定）' if straight else 'スタート〜1コーナー（想定）',
             'goal': '進行方向' if straight else '1コーナーへ', 'horses': pack(scene1)},
            {'key': 'stretch', 'title': 'ゴール前（想定）' if straight else '最後の直線（想定）',
             'goal': 'ゴール', 'horses': pack(scene2)},
        ],
    }


def summary(diagram, scene_key, top=4):
    """図の先頭から数頭を「10番ウェイワードアクト」の形で（コラム本文の材料用）"""
    for s in (diagram or {}).get('scenes', []):
        if s['key'] == scene_key:
            return [f"{h['num']}番{h['name']}" for h in s['horses'][:top]]
    return []
