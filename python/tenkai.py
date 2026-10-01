"""
tenkai.py — 展開想定図の「根拠」になる数値をまとめて扱う

  ・馬ごとの材料（近走の成績表から。追加リクエストなし）
      c1        … 序盤の平均位置。通過順の最初の値（最初に記録されたコーナー）を
                    (順位−1)÷(頭数−1) にしたもの（0=先頭〜1=最後方。頭数が違うレース同士でも先頭は常に0）
                    ※ 1200m などは3コーナーから、長距離で5つ以上コーナーがあると最後の4つだけが記録される
      c4        … 終盤の平均位置（通過順の最後の値＝最後に記録されたコーナー。同上）
      kick      … 上がり3F が「そのレースの後半3F」より何秒速かったかの平均（+ほど終いが速い）。
                    レースごとの流れに対する相対値で、馬場・距離の違う上がりタイムを直接比べたものではない
      gain      … 最後に記録された通過順からゴールまでに上げた順位の平均（÷頭数。+ほど追い上げる）
      nige_rate … 最初のコーナーを1番手で回った割合
  ・結果ページ（db.netkeiba.com/race/<id>/）から、実際の通過順・上がり・前後半3F を読む
  ・実際のペース（前半3F − 後半3F をコースの平均と比べて ハイ／平均／スロー）
  ・騎手の先行傾向・コース別の傾向（python/data/tenkai_stats.json。tenkai_collect.py で作る）

画面にもコラムにも、ここで計算した数値をそのまま「根拠」として出す。
"""
from __future__ import annotations

import json
import os
import re

VENUES = {'01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
          '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'}
RECENT_N = 6             # 材料に使う直近の走数
PACE_BAND = 0.8          # コース平均より前半が この秒数以上 速ければハイ、遅ければスロー
STATS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'tenkai_stats.json')
_stats_cache = None


# ── 小物 ────────────────────────────────────────────
def parse_passing(passing):
    """'13-12-12-7' → [13, 12, 12, 7]。取れなければ []"""
    return [int(p) for p in str(passing or '').split('-') if p.strip().isdigit()]


def parse_pace(cell):
    """成績表の「ペース」列 '36.8-36.1' → (前半, 後半3F)。取れなければ (None, None)。
    netkeiba の前半の値は「最初の3区間」の合計で、距離が 200m で割り切れないコース（1700m など）は
    最初の区間が 100m のため 500m 分になる（front_meters 参照）。換算はせず、ペースの判定は
    同じコースの平均との差で行うので、コースごとの区間の違いは打ち消される"""
    m = re.match(r'\s*(\d+\.\d)\s*-\s*(\d+\.\d)', cell or '')
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)


def front_meters(distance):
    """「前半」の値が何m分か（最初の区間が 100m のコースは 500m）"""
    return 500 if distance and distance % 200 == 100 else 600


def ratio(pos, field):
    """通過順位 → 0（先頭）〜1（最後方）"""
    return min(1.0, (pos - 1) / (field - 1)) if field > 1 else 0.0


def to_position(r, field):
    """0〜1 の位置 → 今回の頭数での「何番手」"""
    return 1 + r * max(0, field - 1)


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def course_key(venue, surface, distance):
    """コース別の集計キー（例: 東京芝1600）"""
    if not venue or not surface or not distance:
        return None
    return f"{venue}{'ダ' if surface.startswith('ダ') else surface[:1]}{distance}"


def venue_of_race_id(race_id):
    return VENUES.get(str(race_id or '')[4:6])


def venue_of_kaisai(cell):
    """成績表の「開催」列 '1札幌8' → '札幌'（地方・海外は None）"""
    name = re.sub(r'\d', '', cell or '')
    return name if name in VENUES.values() else None


# ── 馬ごとの材料 ──────────────────────────────────────
def horse_features(results, before=None, n=RECENT_N):
    """直近の成績（新しい順。stats_predictor.fetch_horse_results の形式）→ 展開の材料。
    before（'YYYY/MM/DD'）を渡すとその日より前の走だけを使う（検証用）。材料が無ければ None"""
    c1s, c4s, kicks, gains, nige = [], [], [], [], 0
    for r in results:
        if before and (r.get('date') or '') >= before:
            continue
        if r.get('surface') == '障害':
            continue
        pos = parse_passing(r.get('passing'))
        field = r.get('horses') or 0
        if not pos or field < 2:
            continue
        c1s.append(ratio(pos[0], field))
        c4s.append(ratio(pos[-1], field))
        nige += pos[0] == 1
        rank = r.get('rank')
        if isinstance(rank, int) and rank <= field:
            gains.append((pos[-1] - rank) / field)
        _, back = parse_pace(r.get('pace'))
        agari = to_float(r.get('agari'))
        if back and agari and 30 <= agari <= 45:
            kicks.append(back - agari)
        if len(c1s) >= n:
            break
    if not c1s:
        return None
    avg = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
    return {'c1': avg(c1s), 'c4': avg(c4s), 'kick': avg(kicks), 'gain': avg(gains),
            'nige_rate': round(nige / len(c1s), 2), 'n': len(c1s)}


# ── 結果ページ ───────────────────────────────────────
def parse_result_soup(soup, race_id=None):
    """db.netkeiba の結果ページ → 実際の展開。
    {'front','back','surface','distance','direction','horses':[{num,waku,horse_id,jockey_id,rank,passing,agari,name,pop,odds}]}"""
    from constants import parse_course
    table = soup.find('table', class_='race_table_01') if soup else None
    if not table:
        return None
    head = [th.get_text(strip=True) for th in table.find('tr').find_all(['th', 'td'])]
    col = lambda name: next((i for i, h in enumerate(head) if h == name), None)
    i_pass, i_agari, i_pop, i_odds = col('通過'), col('上り'), col('人気'), col('単勝')
    horses = []
    for tr in table.find_all('tr')[1:]:
        tds = tr.find_all('td')
        if len(tds) < 8:
            continue
        link = tds[3].find('a', href=re.compile(r'/horse/'))
        jl = tr.find('a', href=re.compile(r'/jockey/'))
        m_rank = re.match(r'(\d+)', tds[0].get_text(strip=True))
        num = tds[2].get_text(strip=True)
        waku = tds[1].get_text(strip=True)
        horses.append({
            'num': int(num) if num.isdigit() else None,
            'waku': int(waku) if waku.isdigit() else None,
            'horse_id': re.search(r'/horse/(\w+)', link['href']).group(1) if link else None,
            'jockey_id': (re.search(r'/jockey/(?:result/recent/)?(\w+)', jl['href']) or [None, None])[1] if jl else None,
            'rank': int(m_rank.group(1)) if m_rank else None,
            'passing': parse_passing(tds[i_pass].get_text(strip=True)) if i_pass is not None and i_pass < len(tds) else [],
            'agari': to_float(tds[i_agari].get_text(strip=True)) if i_agari is not None and i_agari < len(tds) else None,
            'name': link.get_text(strip=True) if link else None,
            'pop': (lambda v: int(v) if v.isdigit() else None)(tds[i_pop].get_text(strip=True))
                   if i_pop is not None and i_pop < len(tds) else None,
            'odds': to_float(tds[i_odds].get_text(strip=True)) if i_odds is not None and i_odds < len(tds) else None,
        })
    text = soup.get_text(' ', strip=True)
    m = re.search(r'ペース[\d.\s-]*\((\d+\.\d-\d+\.\d)\)', text)
    intro = soup.find('div', class_='data_intro')
    intro_text = intro.get_text(' ', strip=True) if intro else ''
    surface, distance = parse_course(intro_text)
    front, back = parse_pace(m.group(1)) if m else (None, None)
    md = re.search(r'(芝|ダ|障)[^\d]*?(右|左|直線)', intro_text)
    mdate = re.search(r'(\d{4})年(\d{2})月(\d{2})日', intro_text)
    return {
        'race_id': race_id,
        'date': f"{mdate.group(1)}/{mdate.group(2)}/{mdate.group(3)}" if mdate else None,
        'front': front, 'back': back, 'front_m': front_meters(distance),
        'surface': surface, 'distance': distance, 'direction': md.group(2) if md else None,
        'venue': venue_of_race_id(race_id), 'horses': horses,
    }


# ── DB ───────────────────────────────────────────────
def ensure_column(conn, column='tenkai'):
    """stats_prediction の TEXT 列（既定は tenkai。近走の事実は recent）を用意する。ALTER は排他ロックを取るので、先に有無を確認し、
    追加するときも lock_timeout で待ちすぎない（face_analyzer_local.ensure_face_columns と同じ方針）。
    用意できたら True"""
    cur = conn.cursor()
    try:
        cur.execute("""SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema()
                       AND table_name = 'stats_prediction' AND column_name = %s""", (column,))
        have = cur.fetchone() is not None
        conn.commit()
        if not have:
            cur.execute("SET lock_timeout = '5s'")
            cur.execute(f"ALTER TABLE stats_prediction ADD COLUMN IF NOT EXISTS {column} TEXT")
            cur.execute("SET lock_timeout = 0")
            conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"  [警告] stats_prediction.{column} 列を用意できませんでした（次回再試行）: {e}")
        return False
    finally:
        cur.close()


# ── 想定ペース（逃げ候補の頭数） ──────────────────────────
def pace_by_leaders(feats, rule):
    """各馬の材料（None 可）と検証で選んだ基準 rule=[ハナ率a, 序盤位置b, ハイの頭数hi, スローの頭数lo]
    → (ペース, 逃げ候補の添字リスト)。逃げ候補 = 近走でハナを切る割合が a 以上 または 序盤の平均位置が b 以内"""
    a, b, hi, lo = rule
    leaders = [i for i, f in enumerate(feats) if f and (f['nige_rate'] >= a or f['c1'] <= b)]
    pace = 'ハイペース' if len(leaders) >= hi else 'スローペース' if len(leaders) <= lo else '平均ペース'
    return pace, leaders


def pace_rule(stats=None):
    """検証で従来の判定より当たると確認できた場合だけ、その基準を返す（無ければ None＝従来の判定）"""
    return ((stats or load_stats()).get('model') or {}).get('pace_rule')


# ── 集計済みの傾向（騎手・コース） ──────────────────────
def load_stats():
    """python/data/tenkai_stats.json（無ければ空）。中身は tenkai_collect.py stats が作る"""
    global _stats_cache
    if _stats_cache is None:
        try:
            with open(STATS_PATH, encoding='utf-8') as f:
                _stats_cache = json.load(f)
        except Exception:
            _stats_cache = {}
    return _stats_cache


def actual_pace(front, back, key=None, stats=None):
    """実際のペース。前半3F−後半3F をそのコースの平均（無ければ全体の平均的な値 0）と比べる"""
    if front is None or back is None:
        return None
    norm = ((stats or {}).get('course') or {}).get(key or '', {}).get('pace_diff')
    diff = (front - back) - (norm if norm is not None else 0.0)
    if diff <= -PACE_BAND:
        return 'ハイペース'
    if diff >= PACE_BAND:
        return 'スローペース'
    return '平均ペース'


def jockey_front(jockey_id, stats=None):
    """騎手の先行傾向（騎乗馬の最初のコーナー平均位置 − その馬自身の平均）。+なら後ろ、−なら前へ行かせる"""
    j = ((stats or load_stats()).get('jockey') or {}).get(str(jockey_id or ''))
    return j['c1_bias'] if j and j.get('n', 0) >= 30 else None


def course_trend(key, stats=None):
    """コース別の傾向 {'front_top3','all_top3','inner_top3','outer_top3','n'}（サンプル不足は None）"""
    c = ((stats or load_stats()).get('course') or {}).get(key or '')
    return c if c and c.get('n', 0) >= 150 else None


# ── 相関（検証用） ────────────────────────────────────
def spearman(a, b):
    """順位相関（-1〜1）。同順位は平均順位。3頭未満は None"""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 3:
        return None

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    ra, rb = ranks([p[0] for p in pairs]), ranks([p[1] for p in pairs])
    n = len(pairs)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return round(cov / (va * vb), 3) if va and vb else None
