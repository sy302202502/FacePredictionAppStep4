"""
tenkai_check.py — 展開想定図の答え合わせ（レース後）

コラムに図を付けたレースについて、結果ページの実際の通過順・着順・前後半3F を取り、図と比べて保存する。
result_auto_fetcher.py が的中記録のために取得した結果ページをそのまま使う（netkeiba への追加アクセスなし）。

  start_top4   … 図1で前の4頭のうち、実際に最初のコーナーを4番手以内で回った頭数
  stretch_top4 … 図2で前の4頭のうち、実際に4着以内だった頭数
  start_corr / finish_corr … 図の並びと実際の並びの順位相関（1 に近いほど想定どおり）
  pace_actual  … 実際のペース（前半3F−後半3F をコースの平均と比べる）

    python3 tenkai_check.py <race_id>  # 手動で1レースやり直す（結果ページを1回だけ読む）
"""
from __future__ import annotations

import json
import sys

import requests
from bs4 import BeautifulSoup

import race_diagram
import tenkai
from constants import HEADERS


def ensure_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tenkai_check (
            race_id      VARCHAR(20) PRIMARY KEY,
            pace_pred    VARCHAR(20),
            pace_actual  VARCHAR(20),
            front3f      DOUBLE PRECISION,
            back3f       DOUBLE PRECISION,
            start_top4   INTEGER,
            stretch_top4 INTEGER,
            start_corr   DOUBLE PRECISION,
            finish_corr  DOUBLE PRECISION,
            actual       TEXT,
            checked_at   TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("ALTER TABLE tenkai_check ADD COLUMN IF NOT EXISTS front_m INTEGER")
    conn.commit()
    cur.close()


def compare(diagram, result, stats=None):
    """保存済みの図（dict）と結果（tenkai.parse_result_soup）→ 答え合わせの数値。比べられなければ None"""
    by_num = {h['num']: h for h in result['horses'] if h.get('num')}
    scenes = {s['key']: s['horses'] for s in diagram.get('scenes', [])}
    start, stretch = scenes.get('start') or [], scenes.get('stretch') or []
    ran = [h for h in by_num.values() if h.get('rank') and h.get('passing')]
    if len(ran) < 5 or not start or not stretch:
        return None
    c1 = {h['num']: h['passing'][0] for h in ran}
    rank = {h['num']: h['rank'] for h in ran}
    start_pred = [h['num'] for h in start if h['num'] in c1]
    stretch_pred = [h['num'] for h in stretch if h['num'] in rank]
    key = tenkai.course_key(result.get('venue'), result.get('surface'), result.get('distance'))
    return {
        'pace_pred': diagram.get('pace'),
        'pace_actual': tenkai.actual_pace(result.get('front'), result.get('back'), key, stats or tenkai.load_stats()),
        'front3f': result.get('front'), 'back3f': result.get('back'), 'front_m': result.get('front_m'),
        'start_top4': sum(1 for n in start_pred[:4] if c1[n] <= 4),
        'stretch_top4': sum(1 for n in stretch_pred[:4] if rank[n] <= 4),
        'start_corr': tenkai.spearman(list(range(len(start_pred))), [c1[n] for n in start_pred]),
        'finish_corr': tenkai.spearman(list(range(len(stretch_pred))), [rank[n] for n in stretch_pred]),
        'actual': {
            'horses': [{'num': h['num'], 'waku': h['waku'], 'c1': h['passing'][0], 'c4': h['passing'][-1],
                        'rank': h['rank'], 'agari': h['agari']} for h in sorted(ran, key=lambda x: x['rank'])],
            'diagram': actual_diagram(diagram, ran),
        },
    }


def actual_diagram(diagram, ran):
    """実際の隊列を、想定図と同じ形（画面でそのまま描ける）にする。
    図1=実際の最初のコーナーの通過順、図2=実際の着順。内外は実際には分からないので想定図と同じ決め方で置く"""
    pred = {h['num']: h for s in diagram.get('scenes', []) for h in s['horses']}
    rows = [dict(pred.get(h['num'], {}), num=h['num'], waku=h['waku'] or pred.get(h['num'], {}).get('waku'),
                 name=pred.get(h['num'], {}).get('name', ''), mark=pred.get(h['num'], {}).get('mark'),
                 style=pred.get(h['num'], {}).get('style'), c1=h['passing'][0], rank=h['rank']) for h in ran]
    n = len(rows)

    def scene(key, title, goal, value, pref, why):
        xs = race_diagram._spread([value(h) for h in rows])
        ordered = sorted(zip(rows, xs), key=lambda t: (t[1], t[0]['num']))
        return {'key': key, 'title': title, 'goal': goal,
                'horses': [{'num': h['num'], 'waku': h['waku'], 'mark': h['mark'], 'style': h['style'],
                            'name': h['name'], 'x': round(x, 3), 'lane': lane, 'why': why(h)}
                           for h, x, lane in race_diagram._assign_lanes(ordered, pref)]}
    pref1 = lambda h: round((h['num'] - 1) / max(1, n - 1) * 3)
    pref2 = lambda h: {'逃げ': 0, '先行': 1, '差し': 3, '追込': 4}.get(h['style'], 2)
    return {'direction': diagram.get('direction'), 'pace': None, 'scenes': [
        scene('start', '実際の最初のコーナー', '最初のコーナー', lambda h: h['c1'], pref1, lambda h: f"実際 {h['c1']}番手"),
        scene('stretch', '実際のゴール', 'ゴール', lambda h: h['rank'], pref2, lambda h: f"実際 {h['rank']}着"),
    ]}


def record(conn, race_id, soup):
    """結果ページ（result_auto_fetcher が的中記録のために取得済みの soup）から答え合わせを保存する。
    netkeiba への追加のアクセスはしない。
    ・コラムの図があるレース … 図と比べた数値もあわせて保存
    ・図が無いレース       … 実際の通過順・着順・前後半だけを保存（後日、重みを見直すときの材料。
                              予想時点の材料は stats_prediction.tenkai に残っている）"""
    if soup is None:
        return
    try:
        ensure_table(conn)
        result = tenkai.parse_result_soup(soup, race_id)
        if not result:
            return
        cur = conn.cursor()
        cur.execute("SELECT diagram FROM race_column WHERE race_id = %s AND diagram IS NOT NULL", (race_id,))
        row = cur.fetchone()
        cur.close()
        diagram = json.loads(row[0]) if row else None
        c = compare(diagram, result) if diagram else None
        if not c:
            key = tenkai.course_key(result.get('venue'), result.get('surface'), result.get('distance'))
            ran = [h for h in result['horses'] if h.get('rank') and h.get('passing')]
            c = {'pace_pred': None, 'start_top4': None, 'stretch_top4': None, 'start_corr': None, 'finish_corr': None,
                 'pace_actual': tenkai.actual_pace(result.get('front'), result.get('back'), key, tenkai.load_stats()),
                 'front3f': result.get('front'), 'back3f': result.get('back'), 'front_m': result.get('front_m'),
                 'actual': {'horses': [{'num': h['num'], 'waku': h['waku'], 'c1': h['passing'][0],
                                        'c4': h['passing'][-1], 'rank': h['rank'], 'agari': h['agari']}
                                       for h in sorted(ran, key=lambda x: x['rank'])]}}
        save(conn, race_id, c)
        if c['start_top4'] is not None:
            print(f"    展開図の答え合わせ: 最初のコーナー前4頭の的中 {c['start_top4']}/4・直線前4頭→4着内 "
                  f"{c['stretch_top4']}/4・ペース 想定{c['pace_pred']}/実際{c['pace_actual']}")
    except Exception as e:
        conn.rollback()
        print(f"    [展開図の答え合わせ] 保存に失敗（的中記録は完了済み）: {e}")


def save(conn, race_id, c):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO tenkai_check (race_id, pace_pred, pace_actual, front3f, back3f, front_m, start_top4, stretch_top4,
                                  start_corr, finish_corr, actual, checked_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        ON CONFLICT (race_id) DO UPDATE SET pace_pred = EXCLUDED.pace_pred, pace_actual = EXCLUDED.pace_actual,
            front3f = EXCLUDED.front3f, back3f = EXCLUDED.back3f, front_m = EXCLUDED.front_m, start_top4 = EXCLUDED.start_top4,
            stretch_top4 = EXCLUDED.stretch_top4, start_corr = EXCLUDED.start_corr,
            finish_corr = EXCLUDED.finish_corr, actual = EXCLUDED.actual, checked_at = NOW()
    """, (race_id, c['pace_pred'], c['pace_actual'], c['front3f'], c['back3f'], c['front_m'], c['start_top4'],
          c['stretch_top4'], c['start_corr'], c['finish_corr'], json.dumps(c['actual'], ensure_ascii=False)))
    conn.commit()
    cur.close()


if __name__ == '__main__':
    # 手動で1レースだけやり直す（結果ページを1回だけ読む）: python3 tenkai_check.py <race_id>
    from result_auto_fetcher import get_conn
    if len(sys.argv) < 2 or not sys.argv[1].isdigit():
        print(__doc__)
        sys.exit(1)
    rid = sys.argv[1]
    r = requests.get(f"https://db.netkeiba.com/race/{rid}/", headers=HEADERS, timeout=15)
    r.encoding = 'EUC-JP'
    conn = get_conn()
    try:
        record(conn, rid, BeautifulSoup(r.text, 'lxml') if r.status_code == 200 else None)
    finally:
        conn.close()
