"""
race_facts.py — 週中コラム（木曜・金曜）の材料になる「事実」を集める

  ・馬ごとの近走の事実（horse_recent）
      stats_predictor が予想のために取得済みの成績表から作る（追加のアクセスなし）。
      stats_prediction.recent に JSON で保存する
  ・過去の同じレースの結果（past_trends）
      grade_race_result（過去の重賞の開催記録）から同名レースの過去5回の race_id を引き、
      結果ページを1レース1回だけ読んで past_race_result に保存する（2回目以降はアクセスなし）

ここで作る文字列（「3着」「8番人気」など）はそのままコラムの材料になり、本文の数字の照合にも使う。
顔面分析の結果は使わない（週中コラムは事実だけで組み立てる）。
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

import tenkai
from constants import HEADERS, polite_sleep

PAST_YEARS = 5          # 過去何回分の同じレースを見るか
RECENT_RUNS = 5         # 保存する近走の数
# 地方競馬の開催地（成績表の「開催」列。これ以外で中央でもないものは海外とみなす）
LOCAL_TRACKS = {'帯広', '門別', '盛岡', '水沢', '浦和', '船橋', '大井', '川崎', '金沢', '笠松', '名古屋',
                '園田', '姫路', '高知', '佐賀', 'ばんえい'}


# ── 馬ごとの近走 ──────────────────────────────────────
def _d(s):
    try:
        return datetime.strptime(s, '%Y/%m/%d').date()
    except (TypeError, ValueError):
        return None


def horse_recent(results, target_surface=None, target_distance=None, asof=None):
    """成績表（新しい順。stats_predictor.fetch_horse_results の形式）→ 近走の事実。
    {'asof','runs':[{date,race,grade,rank,field,pop,surface,distance,cond}],'grade_wins':{'G1':n,..},
     'same':{'label','starts','wins','top3'}}。成績が無ければ None"""
    flat = [r for r in results if r.get('surface') != '障害' or target_surface == '障害']
    if not flat:
        return None
    runs = [{'date': r['date'], 'race': r['race_name'], 'grade': r.get('grade'), 'rank': r['rank'],
             'field': r['horses'], 'pop': r.get('popularity'), 'surface': r['surface'],
             'distance': r['distance'], 'cond': r.get('condition'), 'venue': r.get('venue')}
            for r in flat[:RECENT_RUNS]]
    gw = {}
    for r in flat:
        if r['rank'] == 1 and r.get('grade') in ('G1', 'G2', 'G3'):
            gw[r['grade']] = gw.get(r['grade'], 0) + 1
    same = None
    if target_surface and target_distance:
        hits = [r for r in flat if r['surface'] == target_surface and abs((r['distance'] or 0) - target_distance) <= 100]
        same = {'label': f"{target_surface}{target_distance - 100}〜{target_distance + 100}m",
                'starts': len(hits), 'wins': sum(1 for r in hits if r['rank'] == 1),
                'top3': sum(1 for r in hits if r['rank'] <= 3)}
    return {'asof': str(asof or date.today()), 'runs': runs, 'grade_wins': gw, 'same': same}


def run_text(r):
    """近走1走 → 「9/14 セントウルS 3着（14頭・8番人気・芝1200m）」。
    海外のレースは開催地を添える（netkeiba の成績表は長いレース名を途中で切るため、
    「チャンピオンズ&チャ(GI)」だけでは何のレースか分からない）"""
    d = _d(r['date'])
    when = f"{d.month}/{d.day}" if d else r['date']
    pop = f"・{r['pop']}番人気" if r.get('pop') and r['pop'] < 30 else ''
    v = re.sub(r'\d', '', r.get('venue') or '')
    where = ''
    if v and not tenkai.venue_of_kaisai(v):           # 中央の開催（例: 4東京2）以外
        where = f"・地方（{v}）" if v in LOCAL_TRACKS else f"・海外（{v}）"
    return f"{when} {r['race']} {r['rank']}着（{r['field']}頭{pop}・{r['surface']}{r['distance']}m{where}）"


def horse_lines(rec, race_date=None):
    """近走の事実 → 材料の文字列のリスト"""
    if not rec or not rec.get('runs'):
        return []
    # 「前走」は最も新しい1走だけ。それより前は「2走前」「3走前」と明記する（取り違えの防止）
    labels = ['前走', '2走前', '3走前']
    out = ['近走: ' + ' / '.join(f"{labels[i]} {run_text(r)}" for i, r in enumerate(rec['runs'][:3]))]
    last = _d(rec['runs'][0]['date'])
    if last and race_date:
        weeks = (race_date - last).days // 7
        out.append(f"前走から{weeks}週" + ('（休み明け）' if weeks >= 10 else ''))
    if rec.get('grade_wins'):
        out.append('重賞勝ち: ' + '・'.join(f"{g} {n}勝" for g, n in sorted(rec['grade_wins'].items())))
    s = rec.get('same')
    if s and s['starts']:
        out.append(f"{s['label']}の成績: {s['starts']}戦{s['wins']}勝・3着以内{s['top3']}回")
    elif s:
        out.append(f"{s['label']}は初めて")
    return out


# ── 過去の同じレース ───────────────────────────────────
def ensure_past_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS past_race_result (
            race_id    VARCHAR(20) PRIMARY KEY,
            race_name  VARCHAR(200),
            race_date  DATE,
            venue      VARCHAR(20),
            data       TEXT,
            fetched_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()


def base_name(name):
    """「毎日王冠(GII)」「毎日王冠（GⅡ）」「毎日王冠」→「毎日王冠」（全角・ローマ数字をそろえ、格付けの括弧と空白を除く）。
    改称されたレースの旧名称は拾えない（その場合は過去の回数が減るだけで、誤った集計にはならない）"""
    t = unicodedata.normalize('NFKC', name or '')      # 全角括弧・Ⅱ などを半角・II に
    t = re.sub(r'\((?:J\.?・?)?(?:G|Jpn)(?:I{1,3}|[123])\)', '', t)
    return re.sub(r'\s+', '', t)


def past_editions(conn, race_name, before):
    """過去の同じレースの (race_id, race_date, venue)。新しい順に最大 PAST_YEARS 件"""
    cur = conn.cursor()
    cur.execute("SELECT race_id, race_name, race_date, venue FROM grade_race_result "
                "WHERE race_date < %s ORDER BY race_date DESC", (before,))
    key = base_name(race_name)
    rows = [(rid, d, v) for rid, n, d, v in cur.fetchall() if rid and base_name(n) == key]
    cur.close()
    return rows[:PAST_YEARS]


def past_result(conn, race_id, race_name, race_date, venue):
    """過去の結果（保存済みならそれを、無ければ結果ページを1回だけ読んで保存）"""
    cur = conn.cursor()
    cur.execute("SELECT data FROM past_race_result WHERE race_id = %s", (race_id,))
    row = cur.fetchone()
    cur.close()
    if row:
        return json.loads(row[0])
    polite_sleep(1.5, 2.5)
    r = requests.get(f"https://db.netkeiba.com/race/{race_id}/", headers=HEADERS, timeout=15)
    if r.status_code != 200:
        return None
    r.encoding = 'EUC-JP'
    data = tenkai.parse_result_soup(BeautifulSoup(r.text, 'lxml'), race_id)
    if not data or not any(h.get('rank') == 1 for h in data['horses']):
        return None
    cur = conn.cursor()
    cur.execute("INSERT INTO past_race_result (race_id, race_name, race_date, venue, data) VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (race_id) DO NOTHING",
                (race_id, race_name, race_date, venue, json.dumps(data, ensure_ascii=False)))
    conn.commit()
    cur.close()
    return data


def _style(h, field):
    """最初のコーナーの位置 → 脚質（逃げ=1番手、先行=前3分の1、差し=中団、追込=後方3分の1）"""
    if not h.get('passing') or field < 2:
        return None
    p = h['passing'][0]
    if p == 1:
        return '逃げ'
    r = (p - 1) / (field - 1)
    return '先行' if r <= 0.33 else '差し' if r <= 0.66 else '追込'


def past_trends(conn, race_name, race_date, venue_now=None, surface_now=None, distance_now=None):
    """過去の同じレースの傾向 → 材料の辞書（文字列）。過去の記録が無ければ None。
    ・芝ダートか距離が今年と違う年は、同名の別条件のレースとみなして使わない
    ・開催場が今年と違う年（改修による代替開催など）は、年ごとの一覧には注記つきで載せるが、
      コースの形に左右される集計（人気・枠・脚質）には混ぜない
    ・人気が取れなかった年は、母数と内訳を合わせるため集計から外し、その数を明記する"""
    ensure_past_table(conn)
    years = []
    for rid, d, venue in past_editions(conn, race_name, race_date):
        try:
            data = past_result(conn, rid, race_name, d, venue)
        except Exception as e:
            print(f"    [過去の結果] {rid} 取得失敗: {e}")
            data = None
        if not data:
            continue
        if surface_now and data.get('surface') and data['surface'] != surface_now:
            continue
        if distance_now and data.get('distance') and data['distance'] != distance_now:
            continue
        years.append((d, tenkai.venue_of_kaisai(venue) or venue, data))   # 「1函館5」→「函館」
    if not years:
        return None

    per_year, same = [], []
    for d, held, data in years:
        hs = [h for h in data['horses'] if h.get('rank')]
        win = next((h for h in hs if h['rank'] == 1), None)
        if not win:
            continue
        st = _style(win, len(data['horses']))
        pas = '-'.join(map(str, win['passing'])) if win.get('passing') else '不明'
        pop = f"{win['pop']}番人気・" if win.get('pop') else ''
        line = f"{d.year}年 {win['name']}（{pop}{win['waku']}枠・通過{pas}" + (f"・{st}" if st else '') + '）'
        if held and venue_now and held != venue_now:
            line += f"（この年は{held}で開催のため下の集計には含めない）"
        else:
            same.append(data)
        per_year.append(line)
    out = {'対象': f"過去{len(years)}回（{years[-1][0].year}〜{years[0][0].year}年）", '年ごとの勝ち馬': per_year}
    if not same:
        return out

    n = len(same)
    head = f"{venue_now}で行われた過去{n}回" if venue_now else f"過去{n}回"
    out['集計の対象'] = head
    with_pop = [d for d in same if any(h.get('pop') for h in d['horses'])]
    fav = [next((h.get('rank') for h in d['horses'] if h.get('pop') == 1), None) for d in with_pop]
    if with_pop:
        out['1番人気の成績'] = (f"1番人気は{len(with_pop)}回で{sum(1 for r in fav if r == 1)}勝・2着{sum(1 for r in fav if r == 2)}回・"
                           f"3着{sum(1 for r in fav if r == 3)}回・4着以下{sum(1 for r in fav if not r or r >= 4)}回"
                           + (f"（人気が分からない{n - len(with_pop)}回は除く）" if len(with_pop) < n else ''))
    top3 = [h for d in same for h in d['horses'] if h.get('rank') and h['rank'] <= 3]
    pops = [h['pop'] for h in top3 if h.get('pop')]
    if pops:
        out['人気'] = (f"3着以内{len(pops)}頭の人気: 1〜3番人気が{sum(1 for p in pops if p <= 3)}頭・"
                     f"4〜6番人気が{sum(1 for p in pops if 4 <= p <= 6)}頭・7番人気以下が{sum(1 for p in pops if p >= 7)}頭")
    wk = [h['waku'] for h in top3 if h.get('waku')]
    if wk:
        out['枠'] = f"3着以内{len(wk)}頭の枠: 1〜4枠が{sum(1 for w in wk if w <= 4)}頭・5〜8枠が{sum(1 for w in wk if w >= 5)}頭"
    styles = {}
    for d in same:
        win = next((h for h in d['horses'] if h.get('rank') == 1), None)
        st = _style(win, len(d['horses'])) if win else None
        if st:
            styles[st] = styles.get(st, 0) + 1
    if styles:
        out['脚質'] = f"勝ち馬{sum(styles.values())}頭の脚質: " + '・'.join(f"{k}{styles.get(k, 0)}頭" for k in ('逃げ', '先行', '差し', '追込'))
    return out
