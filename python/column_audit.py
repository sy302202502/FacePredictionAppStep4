"""
column_audit.py — 公開しているコラムを「実際に表示されるページ」で監査する（公開前の最後の関門）

    python3 python/column_audit.py <race_id> [--base URL] [--week thu|fri]
    （終了コード 0=合格 / 1=不合格。不合格の理由を1行ずつ表示）

文章を作る側の検査（column_writer / week_column）とは別に、出来上がったページそのものを読んで確かめる。
読み手が見るものだけを相手にするので、作る側のどこかに不具合があっても、ここで止まる。
夜のコラム（night_columns.py）と、X 投稿の用意（Mac の定時タスク）の両方が、この監査に通ったものだけを先へ進める。

鬼眼コラム（/predict-v2?raceId=…）で確かめること:
  1. 本文の印（◎は「◎は6番」「◎6番」どちらの書き方も）が、予想画面のカードの印と1頭も違わない
  2. 本文の頭数（「17頭」）が、カードの数と同じ
  3. 展開図: 丸の数＝カードの数、図の印＝カードの印、丸の色＝カードの枠、
     内ラチの向き＝競馬場の回り（東京・新潟・中京=左回り=上、ほかの中央の競馬場=右回り=下）
  4. 馬場を「（確定）」と書いてよいのはレース当日だけ
  5. 情報元・第三者の名前、語り口に合わない言葉、結果を保証する言い方が無い
週中コラム（/column の #race-<race_id>）で確かめること:
  2・5 に加えて、印（◎○▲△注）と顔つきの話が無いこと
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

VENUES = {'01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
          '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'}
LEFT = {'東京', '新潟', '中京'}
WAKU_FILL = {'#ffffff': 1, '#222222': 2, '#e53935': 3, '#1e5bd8': 4,
             '#fdd835': 5, '#2e9e44': 6, '#f57c00': 7, '#f48fb1': 8}
MARKS = ('◎', '○', '▲', '△', '注')
NG_WORDS = ('netkeiba', 'ネットケイバ', 'ネット競馬', '気象庁', '東スポ', '東京スポーツ', 'Gemini', 'ChatGPT',
            '僕', '俺', 'みなさん', '皆さん', 'だよ', 'じゃん', '絶対', '確実', '鉄板', '必ず勝')
RAIL_STROKE = '#e8f5e0'
DEFAULT_BASE = os.getenv('APP_INTERNAL_URL') or os.getenv('APP_PUBLIC_URL') or 'http://localhost:8081'


def _today():
    return datetime.now(timezone(timedelta(hours=9))).date()


def _get(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, 'lxml')


def _race_date(soup, race_id):
    """レース選択の「10/04　毎日王冠」から日付（年は race_id の先頭4桁）"""
    opt = soup.select_one(f'option[value="{race_id}"]')
    m = re.match(r'\s*(\d{1,2})/(\d{1,2})', opt.get_text() if opt else '')
    return datetime(int(race_id[:4]), int(m.group(1)), int(m.group(2))).date() if m else None


def _cards(soup):
    """予想画面のカード → {馬番: {'mark', 'waku', 'name'}}"""
    out = {}
    for c in soup.select('div.horse-card'):
        num = c.select_one('.horse-number-badge')
        if not num:
            continue
        n = int(re.sub(r'\D', '', num.get_text()))
        mark = c.select_one('.rank-mark')
        waku = c.select_one('.waku-badge')
        out[n] = {'mark': mark.get_text(strip=True) if mark else None,
                  'waku': int(waku.get_text(strip=True)) if waku and waku.get_text(strip=True).isdigit() else None,
                  'name': (c.select_one('.horse-name') or c).get_text(strip=True)}
    return out


def _text_marks(text):
    """本文の印 → {印: 馬番}（「◎は6番」「◎6番」「○16番」）"""
    out = {}
    for mk, n in re.findall(r'([◎○▲△注])(?:は|\s)*(\d{1,2})番', text):
        out.setdefault(mk, int(n))
    return out


def _common(text, problems):
    for w in NG_WORDS:
        if w in text:
            problems.append(f'使わない言葉「{w}」がある')


def audit_race_column(race_id, base=DEFAULT_BASE):
    """鬼眼コラムの監査 → 問題のリスト（空なら合格）"""
    problems = []
    soup = _get(f'{base}/predict-v2?raceId={race_id}')
    col = soup.select_one('.column-card')
    if not col:
        return ['鬼眼コラムが表示されていない']
    body = ' '.join(p.get_text() for p in col.select('.column-p'))
    title = (col.select_one('.column-title') or col).get_text()
    cards = _cards(soup)
    card_marks = {v['mark']: n for n, v in cards.items() if v['mark'] in MARKS}

    # 1. 印
    tm = _text_marks(body)
    for mk, n in tm.items():
        if card_marks.get(mk) != n:
            problems.append(f'本文の{mk}{n}番と、カードの{mk}（{card_marks.get(mk)}番）が違う')
    if '◎' not in tm:
        problems.append('本文に◎が見つからない')
    # 本文の「N番馬名」の馬名がカードと同じか
    for n, name in re.findall(r'(\d{1,2})番([ァ-ヴー]{2,})', body):
        c = cards.get(int(n))
        if not c:
            problems.append(f'本文の{n}番は出走馬にいない')
        elif not (c['name'].startswith(name) or name.startswith(c['name'])):
            problems.append(f'本文の{n}番{name}と、カードの{n}番{c["name"]}が違う')
    # 2. 頭数
    m = re.search(r'(\d{1,2})頭の戦い|(\d{1,2})頭が出走|(\d{1,2})頭立て', body)
    if m:
        hc = int(next(g for g in m.groups() if g))
        if hc != len(cards):
            problems.append(f'本文の頭数 {hc}頭 と、出走馬カード {len(cards)}頭 が違う')
    # 3. 展開図
    venue = VENUES.get(race_id[4:6])
    for i, svg in enumerate(col.select('.diagram svg'), 1):
        horses = svg.select('g.dg-horse')
        if len(horses) != len(cards):
            problems.append(f'図{i}の丸 {len(horses)}頭 と、カード {len(cards)}頭 が違う')
        dmarks = {}
        for g in horses:
            texts = g.find_all('text')
            n = int(texts[0].get_text())
            if len(texts) > 1 and texts[1].get_text() in MARKS:
                dmarks[texts[1].get_text()] = n
            fill = (g.find('circle') or {}).get('fill')
            wk = cards.get(n, {}).get('waku')
            if wk and WAKU_FILL.get(fill) != wk:
                problems.append(f'図{i}の{n}番の丸の色が枠（{wk}枠）と違う')
        if dmarks != card_marks:
            problems.append(f'図{i}の印 {dmarks} と、カードの印 {card_marks} が違う')
        rail = next((l for l in svg.find_all('line') if l.get('stroke') == RAIL_STROKE), None)
        straight = '直後' in (svg.get('aria-label') or '') or 'ゴール前' in (svg.get('aria-label') or '')
        if venue and rail is not None and not straight:
            top = int(float(rail.get('y1'))) < 100
            if top != (venue in LEFT):
                problems.append(f'図{i}の内ラチが{"上" if top else "下"}（{venue}は{"左" if venue in LEFT else "右"}回りなので'
                                f'{"上" if venue in LEFT else "下"}が正しい）')
    # 4. 馬場の「確定」
    rd = _race_date(soup, race_id)
    if '（確定）' in body and rd and rd > _today():
        problems.append(f'レース前日以前（{rd}）なのに馬場を「確定」と書いている')
    # 5. 言葉
    _common(title + body, problems)
    return problems


def audit_week_column(race_id, base=DEFAULT_BASE):
    """週中コラムの監査 → 問題のリスト（空なら合格）。頭数は予想画面のカードと比べる"""
    problems = []
    card = _get(f'{base}/column').select_one(f'#race-{race_id} .card-inner')
    if not card:
        return ['週中コラムが表示されていない']
    # 本文は最新の版だけ（前の版は「木曜版を読む」の中）
    body = ' '.join(p.get_text() for p in card.select('.col-p') if not p.find_parent('details'))
    title = (card.select_one('.col-title') or card).get_text()
    # 印: ◎○▲△ は記号そのもの、「注」は「注10番」のように馬番が続くときだけ（「注目」は除く）
    for mk in ('◎', '○', '▲', '△'):
        if mk in body:
            problems.append(f'週中コラムに印「{mk}」がある')
    if re.search(r'注\s*\d{1,2}番', body):
        problems.append('週中コラムに印「注」がある')
    for w in ('顔', '目つき', '眼差し'):
        if w in body:
            problems.append(f'週中コラムに顔の話「{w}」がある')
    m = re.search(r'(\d{1,2})頭が(?:出走|登録)', body)
    if m:
        n_cards = len(_cards(_get(f'{base}/predict-v2?raceId={race_id}')))
        if n_cards and int(m.group(1)) != n_cards and '出走予定' not in body:
            problems.append(f'本文の頭数 {m.group(1)}頭 と、出走馬 {n_cards}頭 が違う')
    _common(title + body, problems)
    return problems


def enforce(conn, race_id, week_edition, rewrite, log=print):
    """公開したコラムを監査し、不合格なら rewrite() で1回だけ書き直して再監査。
    それでも不合格なら公開を取り下げる（行を消す）。戻り値: (合格したか, 問題のリスト)
    week_edition: 週中コラムなら 'thu' / 'fri'、鬼眼コラムなら None"""
    def check():
        try:
            return audit_week_column(race_id) if week_edition else audit_race_column(race_id)
        except Exception as e:
            return [f'監査を実行できなかった: {e}']
    problems = check()
    if problems and rewrite:
        log(f"  ⚠️ 監査 不合格 → 書き直して再監査: {' / '.join(problems)}")
        rewrite()
        problems = check()
    if problems:
        cur = conn.cursor()
        if week_edition:
            cur.execute("DELETE FROM week_column WHERE race_id = %s AND edition = %s", (race_id, week_edition))
        else:
            cur.execute("DELETE FROM race_column WHERE race_id = %s", (race_id,))
        conn.commit()
        cur.close()
        log(f"  ⛔ 監査に通らないため公開を取り下げました: {' / '.join(problems)}")
        return False, problems
    return True, []


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        print(__doc__)
        sys.exit(2)
    base = sys.argv[sys.argv.index('--base') + 1].rstrip('/') if '--base' in sys.argv else DEFAULT_BASE
    rid = args[0]
    problems = audit_week_column(rid, base) if '--week' in sys.argv else audit_race_column(rid, base)
    if problems:
        print(f"監査 不合格（{rid}）")
        for p in problems:
            print(f"  ✗ {p}")
        print('RESULT:{"success": false}')
        sys.exit(1)
    print(f"監査 合格（{rid}）")
    print('RESULT:{"success": true}')


if __name__ == '__main__':
    main()
