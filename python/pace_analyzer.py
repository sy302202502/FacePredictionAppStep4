"""pace_analyzer.py — 通過順位から脚質を判定し、レースの展開を想定する

netkeiba の馬別成績テーブルに含まれる「通過」（例 13-12-12-7）を使う。
このデータは fetch_horse_results() が取得済みのHTMLに元から入っているため、
追加のリクエストは一切発生しない。

  1. running_style()  : 1頭の直近成績 → 脚質（逃げ/先行/差し/追込）
  2. predict_pace()   : 出走全頭の脚質 → 想定ペース
  3. pace_adjustment(): 脚質 × 想定ペース → スコア補正（±5pt）

※ 展開は当日の枠順・馬場・騎手心理で容易に変わる。補正幅を±5ptに抑えて
   あるのは、外れたときの被害を限定するため。
"""

STYLES = ('逃げ', '先行', '差し', '追込')

# 先行度（1コーナー通過順位 / 頭数）の境界
_RATIO_SENKO = 0.33
_RATIO_SASHI = 0.66
# 「逃げ」と判定する、1番手通過の割合
_NIGE_RATE = 0.5
# 判定に使う直近走数
_RECENT_N = 6

# 想定ペース × 脚質 → 補正pt
_ADJUST = {
    'ハイペース':  {'逃げ': -3.5, '先行': -1.5, '差し': 2.5, '追込': 3.5},
    '平均ペース':  {'逃げ':  0.5, '先行':  1.0, '差し': 0.0, '追込': -1.0},
    'スローペース': {'逃げ':  3.5, '先行':  2.0, '差し': -1.5, '追込': -3.0},
}
# ダートの道悪は前が止まりにくい（芝は一定しないので補正しない）
_DIRT_WET_BONUS = {'逃げ': 1.0, '先行': 1.0, '差し': -0.5, '追込': -0.5}
_ADJUST_CAP = 5.0


def _parse_passing(passing):
    """'13-12-12-7' → [13,12,12,7]。取れなければ []。"""
    if not passing:
        return []
    out = []
    for part in str(passing).split('-'):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def running_style(results, recent_n=_RECENT_N):
    """直近成績から脚質を判定。

    returns: {'style', 'ratio', 'samples', 'nige_rate', 'agari'} / データ不足なら None
    """
    ratios, nige_hits, agaris = [], 0, []
    for r in results:
        pos = _parse_passing(r.get('passing'))
        horses = r.get('horses') or 0
        if not pos or horses < 2:
            continue
        early = pos[0]
        ratios.append(min(1.0, early / horses))
        if early == 1:
            nige_hits += 1
        a = r.get('agari')
        try:
            if a:
                agaris.append(float(a))
        except (TypeError, ValueError):
            pass
        if len(ratios) >= recent_n:
            break

    if not ratios:
        return None

    mean_ratio = sum(ratios) / len(ratios)
    nige_rate  = nige_hits / len(ratios)

    if nige_rate >= _NIGE_RATE:
        style = '逃げ'
    elif mean_ratio <= _RATIO_SENKO:
        style = '先行'
    elif mean_ratio <= _RATIO_SASHI:
        style = '差し'
    else:
        style = '追込'

    return {
        'style':     style,
        'ratio':     round(mean_ratio, 3),
        'samples':   len(ratios),
        'nige_rate': round(nige_rate, 2),
        'agari':     round(sum(agaris) / len(agaris), 1) if agaris else None,
    }


def predict_pace(styles):
    """出走各馬の脚質リスト → 想定ペース。

    styles: ['逃げ','先行',None,...]（None＝判定不能）
    returns: {'pace', 'counts', 'reason'}
    """
    counts = {s: 0 for s in STYLES}
    for s in styles:
        if s in counts:
            counts[s] += 1
    nige, senko = counts['逃げ'], counts['先行']
    known = sum(counts.values())

    if known < 4:
        return {'pace': '平均ペース', 'counts': counts,
                'reason': f'脚質を判定できた馬が{known}頭のみ → 中立扱い'}

    if nige >= 3 or (nige >= 2 and senko >= 3):
        pace, why = 'ハイペース', f'逃げ{nige}頭・先行{senko}頭で先行争いが激化'
    elif nige == 0 or (nige == 1 and senko <= 2):
        pace, why = 'スローペース', f'逃げ{nige}頭・先行{senko}頭で前が楽に運べる'
    else:
        pace, why = '平均ペース', f'逃げ{nige}頭・先行{senko}頭'

    return {'pace': pace, 'counts': counts, 'reason': why}


def pace_adjustment(style, pace, surface=None, condition=None):
    """脚質 × 想定ペース → スコア補正pt と説明文。

    surface/condition を渡すとダートの道悪補正が乗る。
    """
    if not style:
        return 0.0, '脚質不明 → 補正なし'

    pt = _ADJUST.get(pace, {}).get(style, 0.0)
    notes = [f'{style}／{pace}']

    if surface == 'ダート' and condition in ('稍重', '重', '不良'):
        bonus = _DIRT_WET_BONUS.get(style, 0.0)
        if bonus:
            pt += bonus
            notes.append(f'ダート{condition}で前残り{"有利" if bonus > 0 else "不利"}')

    pt = max(-_ADJUST_CAP, min(_ADJUST_CAP, pt))
    sign = '+' if pt >= 0 else ''
    return round(pt, 1), f'{"・".join(notes)} → {sign}{pt:.1f}pt'
