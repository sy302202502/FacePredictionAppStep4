"""
tenkai_backtest.py — 展開想定図の作り方を、過去レースの「実際の通過順・着順」で検証して重みを決める

    python3 tenkai_backtest.py [--scores <予想JSONのdir>] [--save]

  材料: tenkai_collect.py が保存した結果ページ（logs/tenkai_cache/results）と各馬の全成績（.../horses）。
        統計スコアの順位は、当時の予想（--scores の <race_id>.json。horses[].stats）から。顔面は使わない。
  手順: 1. 各レースの前日までの成績だけで材料（tenkai.horse_features）を作る（未来の情報を混ぜない）
        2. 騎手・コースの傾向も、検証期間より前（2026/01/01 より前）の走だけで集計する
        3. レースを2つに分け、片方で重みを選び、もう片方で成績を測る（選んだデータで測ると甘くなるため）
        4. 従来の方法（脚質と平均通過順だけ）と比べる
  --save で、選んだ重みの成績とペース判定の的中率を python/data/tenkai_stats.json の 'model' に書く
  （重み W そのものは race_diagram.py に手で反映する。検証結果を見てから決めるため）。
"""
from __future__ import annotations

import argparse
import glob
import itertools
import json
import os

import race_diagram
import tenkai
import tenkai_collect

CACHE = tenkai_collect.CACHE
TRAIN_BEFORE = '2026/01/01'


def load_races(scores_dir):
    races = []
    for p in sorted(glob.glob(os.path.join(CACHE, 'results', '*.json'))):
        with open(p, encoding='utf-8') as f:
            res = json.load(f)
        if not res.get('date') or res.get('surface') == '障害':
            continue
        scores = {}
        sp = os.path.join(scores_dir, f"{res['race_id']}.json") if scores_dir else None
        if sp and os.path.exists(sp):
            with open(sp, encoding='utf-8') as f:
                for h in json.load(f).get('horses', []):
                    # 展開図の位置には統計スコアだけを使う（顔面分析は位置取りに使わない）
                    if h.get('horse_id') and h.get('stats') is not None:
                        scores[h['horse_id']] = h['stats']
        horses, have = [], 0
        for h in res['horses']:
            if not h.get('num') or not h.get('rank') or not h.get('passing'):
                continue
            hp = os.path.join(CACHE, 'horses', f"{h['horse_id']}.json")
            feats = None
            if os.path.exists(hp):
                have += 1
                with open(hp, encoding='utf-8') as f:
                    feats = tenkai.horse_features(json.load(f), before=res['date'])
            horses.append(dict(h, tenkai=feats, stats_score=scores.get(h['horse_id']),
                               style=_style(feats), mark=None, name=''))
        if len(horses) >= 6 and have >= 0.9 * len(horses):
            res['runners'] = horses
            races.append(res)
    return races


def _style(f):
    """材料 → 脚質（pace_analyzer.running_style と同じ境界）"""
    if not f:
        return None
    if f['nige_rate'] >= 0.5:
        return '逃げ'
    return '先行' if f['c1'] <= 0.33 else '差し' if f['c1'] <= 0.66 else '追込'


# ── 並びの計算 ────────────────────────────────────────
def predict(race, w, stats, pace, baseline=False):
    hs = race['runners']
    n = len(hs)
    if baseline:
        # 従来の方法: 平均通過順（無ければ脚質）＋ 逃げは先頭固定、直線は位置と統計スコアの順位を半々
        early = []
        for h in hs:
            f = h['tenkai']
            e = f['c1'] if f else race_diagram._STYLE_EARLY.get(h['style'], 0.5)
            early.append(min(e, 0.08) if h['style'] == '逃げ' else e)
        st = race_diagram.strengths(hs)
        wp = {'ハイペース': 0.35, 'スローペース': 0.65}.get(pace, 0.5)
        cb = {'ハイペース': -0.12, 'スローペース': 0.08}.get(pace, 0.0)
        late = [wp * early[i] + (1 - wp) * st[h['num']] + (cb if h['style'] in ('差し', '追込') else 0)
                for i, h in enumerate(hs)]
        return early, late
    trend = tenkai.course_trend(tenkai.course_key(race['venue'], race['surface'], race['distance']), stats)
    early = [race_diagram.early_score(h, n, w, stats) for h in hs]
    st = race_diagram.strengths(hs)
    late = [race_diagram.late_score(h, n, early[i], st[h['num']], pace, trend, w) for i, h in enumerate(hs)]
    return early, late


def score(races, w, stats, paces, baseline=False):
    """平均の 順位相関（1コーナー・着順）と 前4頭の的中頭数"""
    s1 = s2 = t1 = t2 = 0.0
    for r in races:
        early, late = predict(r, w, stats, paces[r['race_id']], baseline)
        hs = r['runners']
        c1 = [h['passing'][0] for h in hs]
        rank = [h['rank'] for h in hs]
        s1 += tenkai.spearman(early, c1) or 0
        s2 += tenkai.spearman(late, rank) or 0
        o1 = sorted(range(len(hs)), key=lambda i: (early[i], hs[i]['num']))[:4]
        o2 = sorted(range(len(hs)), key=lambda i: (late[i], hs[i]['num']))[:4]
        t1 += sum(1 for i in o1 if c1[i] <= 4)
        t2 += sum(1 for i in o2 if rank[i] <= 4)
    k = max(1, len(races))
    return {'start_corr': round(s1 / k, 3), 'finish_corr': round(s2 / k, 3),
            'start_top4': round(t1 / k, 2), 'stretch_top4': round(t2 / k, 2)}


# ── ペース ──────────────────────────────────────────
def pace_rule(hs, a, b, hi, lo):
    """逃げ候補の頭数でペースを決める（本番と同じ tenkai.pace_by_leaders）"""
    return tenkai.pace_by_leaders([h['tenkai'] for h in hs], [a, b, hi, lo])[0]


def pace_eval(races, pred, actual):
    hit = sum(1 for r in races if pred[r['race_id']] == actual[r['race_id']])
    by = {}
    for label in ('ハイペース', '平均ペース', 'スローペース'):
        rs = [r for r in races if pred[r['race_id']] == label]
        if rs:
            by[label] = round(sum(1 for r in rs if actual[r['race_id']] == label) / len(rs), 2)
    return round(hit / max(1, len(races)), 3), by


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scores', default=os.path.join(tenkai_collect.ROOT, 'logs', 'audit_2026-09-28', 'backtest', 'races'))
    ap.add_argument('--save', action='store_true')
    a = ap.parse_args()

    stats = tenkai_collect.build_stats(before=TRAIN_BEFORE)
    races = [r for r in load_races(a.scores) if r['date'] >= TRAIN_BEFORE]
    print(f"検証レース: {len(races)}（傾向の集計は {TRAIN_BEFORE} より前の {stats['runs']}走）")
    if len(races) < 30:
        print('レースが少なすぎます（収集の途中？）')
        return
    actual = {r['race_id']: tenkai.actual_pace(r['front'], r['back'],
                                               tenkai.course_key(r['venue'], r['surface'], r['distance']), stats)
              for r in races}
    dist = {p: sum(1 for v in actual.values() if v == p) for p in ('ハイペース', '平均ペース', 'スローペース', None)}
    print(f"実際のペース: {dist}")

    # 2つに分ける（race_id の末尾の偶奇。開催・距離が偏らない）
    A = [r for r in races if int(r['race_id'][-1]) % 2 == 0]
    B = [r for r in races if int(r['race_id'][-1]) % 2 == 1]

    # ── ペース判定（方式もしきい値も前半 A だけで選ぶ。後半 B は最後の評価に1回だけ使う） ──
    from pace_analyzer import predict_pace
    old = {r['race_id']: predict_pace([h['style'] for h in r['runners']])['pace'] for r in races}
    acc_old_a, _ = pace_eval(A, old, actual)
    best = None
    for pa, pb, hi, lo in itertools.product((0.34, 0.5), (0.0, 0.05, 0.1, 0.15), (2, 3, 4), (0, 1)):
        pred = {r['race_id']: pace_rule(r['runners'], pa, pb, hi, lo) for r in A}
        acc, _ = pace_eval(A, pred, actual)
        if not best or acc > best[0]:
            best = (acc, (pa, pb, hi, lo))
    params = best[1]
    use_new = best[0] > acc_old_a
    new = {r['race_id']: pace_rule(r['runners'], *params) for r in races}
    paces = new if use_new else old
    acc_old, by_old = pace_eval(B, old, actual)
    acc_new, by_new = pace_eval(B, new, actual)
    majority = max(dist, key=lambda k: dist[k] if k else -1)
    acc_major = round(sum(1 for r in B if actual[r['race_id']] == majority) / max(1, len(B)), 3)
    print(f"\nペース判定 A での選択: 従来 {acc_old_a:.0%} / 新ルール{params} {best[0]:.0%} → {'新' if use_new else '従来'}を採用")
    print(f"ペース判定 B（評価）: 従来 {acc_old:.0%} {by_old} / 新 {acc_new:.0%} {by_new} / "
          f"常に「{majority}」と言う場合 {acc_major:.0%}")

    # ── 図の重み ──
    base = dict(race_diagram.W)
    print(f"\n従来の方法: 全体 {score(races, base, stats, paces, baseline=True)}")
    print(f"現在の W  : 全体 {score(races, base, stats, paces)}")

    best1 = None
    for nige, jk, wk in itertools.product((0, 0.05, 0.1, 0.2, 0.3), (0, 0.5, 1.0, 1.5), (-0.1, -0.05, 0, 0.05, 0.1)):
        w = dict(base, nige=nige, jockey=jk, waku=wk)
        s = score(A, w, stats, paces)['start_corr']
        if not best1 or s > best1[0]:
            best1 = (s, w)
    w1 = best1[1]
    best2 = None
    for c4, kick, stg, pc, cs in itertools.product((0, 0.25, 0.5, 0.75, 1.0), (0, 0.05, 0.1, 0.2),
                                                  (0, 0.25, 0.5, 0.75, 1.0), (0, 0.1, 0.2), (0, 0.1, 0.2)):
        if c4 == 0 and stg == 0:
            continue
        w = dict(w1, c4=c4, kick=kick, strength=stg, pace=pc, course=cs)
        s = score(A, w, stats, paces)['finish_corr']
        if not best2 or s > best2[0]:
            best2 = (s, w)
    w2 = best2[1]
    print(f"\n選んだ重み（前半 {len(A)}レースで選択）: { {k: w2[k] for k in race_diagram.W} }")
    held_base = score(B, base, stats, paces, baseline=True)
    held_new = score(B, w2, stats, paces)
    print(f"検証（後半 {len(B)}レース） 従来: {held_base}")
    print(f"検証（後半 {len(B)}レース） 新  : {held_new}")
    # 参考: 統計スコアの順位だけ／位置だけ
    print(f"参考 統計スコアの順位だけ: {score(B, dict(w2, c4=0, kick=0, pace=0, course=0, strength=1), stats, paces)}")
    print(f"参考 位置と末脚だけ: {score(B, dict(w2, strength=0), stats, paces)}")

    if a.save:
        # アプリが読む傾向は全期間で集計し直し、検証の成績（後半の値）を添える
        full = tenkai_collect.build_stats()
        full['model'] = dict(held_new, races=len(B), base_start_corr=held_base['start_corr'],
                             base_finish_corr=held_base['finish_corr'], weights={k: w2[k] for k in race_diagram.W},
                             pace_rule=list(params) if use_new else None,
                             pace_accuracy=by_new if use_new else by_old,
                             pace_total=acc_new if use_new else acc_old)
        tenkai_collect._save(tenkai.STATS_PATH, full)
        print(f"\n保存: {tenkai.STATS_PATH}")


if __name__ == '__main__':
    main()
