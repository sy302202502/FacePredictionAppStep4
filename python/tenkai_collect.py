"""
tenkai_collect.py — 展開想定図の検証と「騎手・コースの傾向」集計のためのデータ収集

    python3 tenkai_collect.py races <race_id ...>        # 結果ページ（通過順・上がり・前後半3F）を保存
    python3 tenkai_collect.py races --from-dir <dir>     # <dir>/*.json のファイル名を race_id として使う
    python3 tenkai_collect.py horses                     # 保存済みレースの出走馬の全成績を保存
    python3 tenkai_collect.py stats [--before 2026/01/01] [--out path]
                                                         # 騎手・コースの傾向を集計して JSON に

【注意】races / horses は netkeiba へ大量にアクセスする（数千ページ）。回線ごとブロックされる恐れがあるため、
        原則として実行しない（2026-09-29 に 730ページで停止した）。検証の材料は本番のパイプラインが
        すでに取得したページから stats_prediction.tenkai（予想時点）と tenkai_check（結果）へ自然にたまるので、
        重みの見直しはそちらを使う。stats は保存済みのデータを集計するだけでアクセスしない。
・読み取りのみ。取得済みはスキップするので、途中で止めても再開できる。
・netkeiba に負荷をかけないよう 1 件ごとに 1.5〜2.5 秒待つ。
・保存先は logs/tenkai_cache/（Git 管理外）。stats の既定の出力は python/data/tenkai_stats.json（アプリが読む）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict

import requests
from bs4 import BeautifulSoup

from constants import HEADERS, decode_netkeiba, polite_sleep, surface_of_distance_cell
import tenkai

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'logs', 'tenkai_cache')


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def collect_races(race_ids):
    done = 0
    for rid in race_ids:
        path = os.path.join(CACHE, 'results', f'{rid}.json')
        if os.path.exists(path):
            continue
        try:
            r = requests.get(f'https://db.netkeiba.com/race/{rid}/', headers=HEADERS, timeout=20)
            r.encoding = 'EUC-JP'
            data = tenkai.parse_result_soup(BeautifulSoup(r.text, 'lxml'), rid) if r.status_code == 200 else None
        except Exception as e:
            print(f'  {rid} 取得失敗: {e}', flush=True)
            data = None
        if data and data['horses']:
            _save(path, data)
            done += 1
            if done % 25 == 0:
                print(f'  レース {done}件', flush=True)
        polite_sleep(1.5, 2.5)
    print(f'レース: 新規 {done}件', flush=True)


def parse_history(html):
    """馬の成績ページ → 全走（新しい順）"""
    soup = BeautifulSoup(html, 'lxml')
    table = soup.find('table', class_='db_h_race_results')
    rows = []
    if not table:
        return rows
    for tr in table.find_all('tr')[1:]:
        tds = tr.find_all('td')
        cols = [td.get_text(strip=True) for td in tds]
        if len(cols) < 28:
            continue
        m_rank = re.match(r'(\d+)', cols[11])
        rl = tds[4].find('a', href=re.compile(r'/race/'))
        jl = tds[12].find('a', href=re.compile(r'/jockey/'))
        rows.append({
            'date': cols[0], 'venue': tenkai.venue_of_kaisai(cols[1]),
            'race_id': (re.search(r'/race/(\w+)', rl['href']) or [None, None])[1] if rl else None,
            'horses': int(cols[6]) if cols[6].isdigit() else 0,
            'waku': int(cols[7]) if cols[7].isdigit() else None,
            'num': int(cols[8]) if cols[8].isdigit() else None,
            'rank': int(m_rank.group(1)) if m_rank else None,
            'jockey_id': (re.search(r'/jockey/(?:result/recent/)?(\w+)', jl['href']) or [None, None])[1] if jl else None,
            'surface': surface_of_distance_cell(cols[14]),
            'distance': int(re.sub(r'\D', '', cols[14])) if re.search(r'\d', cols[14]) else None,
            'condition': cols[16], 'passing': cols[25], 'pace': cols[26], 'agari': cols[27],
        })
    return rows


def collect_horses():
    # 新しいレースから順に、そのレースの出走馬をまとめて取る（途中でも「全頭そろったレース」から検証できる）
    ids = []
    for p in sorted(glob.glob(os.path.join(CACHE, 'results', '*.json')), reverse=True):
        with open(p, encoding='utf-8') as f:
            ids += [h['horse_id'] for h in json.load(f)['horses'] if h.get('horse_id')]
    ids = list(dict.fromkeys(ids))
    todo = [h for h in ids if not os.path.exists(os.path.join(CACHE, 'horses', f'{h}.json'))]
    print(f'馬: 全{len(ids)}頭（未取得 {len(todo)}頭）', flush=True)
    for i, hid in enumerate(todo, 1):
        try:
            r = requests.get(f'https://db.netkeiba.com/horse/result/{hid}/', headers=HEADERS, timeout=20)
            if r.status_code == 200:
                _save(os.path.join(CACHE, 'horses', f'{hid}.json'), parse_history(decode_netkeiba(r)))
        except Exception as e:
            print(f'  {hid} 取得失敗: {e}', flush=True)
        if i % 100 == 0:
            print(f'  馬 {i}/{len(todo)}', flush=True)
        polite_sleep(1.5, 2.5)
    print('馬: 完了', flush=True)


def build_stats(before=None):
    """保存済みの全成績から 騎手の先行傾向・コース別の傾向 を集計する。
    before を渡すとその日より前の走だけを使う（検証で未来の情報が混ざらないように）"""
    runs = []
    for p in glob.glob(os.path.join(CACHE, 'horses', '*.json')):
        with open(p, encoding='utf-8') as f:
            hist = json.load(f)
        mine = []
        for r in hist:
            if (before and r['date'] >= before) or r['surface'] == '障害' or not r['venue']:
                continue
            pos = tenkai.parse_passing(r['passing'])
            if not pos or r['horses'] < 5:
                continue
            mine.append(dict(r, c1=tenkai.ratio(pos[0], r['horses'])))
        if mine:
            own = sum(x['c1'] for x in mine) / len(mine)
            for x in mine:
                x['own_c1'] = own
            runs.extend(mine)

    jockey = defaultdict(list)
    for x in runs:
        if x['jockey_id']:
            jockey[x['jockey_id']].append(x['c1'] - x['own_c1'])

    course = defaultdict(lambda: {'pace': {}, 'n': 0, 'top3': 0, 'front_n': 0, 'front_top3': 0,
                                  'inner_n': 0, 'inner_top3': 0, 'outer_n': 0, 'outer_top3': 0})
    for x in runs:
        key = tenkai.course_key(x['venue'], x['surface'], x['distance'])
        if not key or not x['rank']:
            continue
        c = course[key]
        top3 = x['rank'] <= 3
        c['n'] += 1
        c['top3'] += top3
        if x['c1'] <= 0.25:
            c['front_n'] += 1
            c['front_top3'] += top3
        if x['waku'] and x['waku'] <= 3:
            c['inner_n'] += 1
            c['inner_top3'] += top3
        elif x['waku'] and x['waku'] >= 6:
            c['outer_n'] += 1
            c['outer_top3'] += top3
        front, back = tenkai.parse_pace(x['pace'])
        if front and x['race_id']:
            c['pace'][x['race_id']] = front - back   # 同じレースは1回だけ数える

    rate = lambda a, b: round(a / b, 3) if b else None
    out_course = {}
    for key, c in course.items():
        diffs = list(c['pace'].values())
        out_course[key] = {
            'n': c['n'], 'races': len(diffs),
            'pace_diff': round(sum(diffs) / len(diffs), 2) if len(diffs) >= 10 else None,
            'all_top3': rate(c['top3'], c['n']), 'front_top3': rate(c['front_top3'], c['front_n']),
            'inner_top3': rate(c['inner_top3'], c['inner_n']), 'outer_top3': rate(c['outer_top3'], c['outer_n']),
        }
    out_jockey = {j: {'n': len(v), 'c1_bias': round(sum(v) / len(v), 3)} for j, v in jockey.items() if len(v) >= 10}
    return {'before': before, 'runs': len(runs), 'course': out_course, 'jockey': out_jockey}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['races', 'horses', 'stats'])
    ap.add_argument('ids', nargs='*')
    ap.add_argument('--from-dir')
    ap.add_argument('--before')
    ap.add_argument('--out', default=tenkai.STATS_PATH)
    a = ap.parse_args()
    if a.cmd == 'races':
        ids = list(a.ids)
        if a.from_dir:
            ids += [os.path.basename(p)[:-5] for p in sorted(glob.glob(os.path.join(a.from_dir, '*.json')))]
        collect_races(ids)
    elif a.cmd == 'horses':
        collect_horses()
    else:
        s = build_stats(a.before)
        _save(a.out, s)
        print(f"集計: {s['runs']}走 / コース {len(s['course'])} / 騎手 {len(s['jockey'])} → {a.out}")


if __name__ == '__main__':
    sys.exit(main())
