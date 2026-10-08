"""
column_audit.py — 公開しているコラムを「実際に表示されるページ」で監査する（公開前の最後の関門）

    python3 python/column_audit.py <race_id> --base URL [--week thu|fri]
    （終了コード 0=合格 / 1=不合格。不合格の理由を1行ずつ表示。--base を省くなら APP_PUBLIC_URL が必須）

文章を作る側の検査（column_writer / week_column）とは別に、出来上がったページそのものを読んで確かめる。
読み手が見るものだけを相手にするので、作る側のどこかに不具合があっても、ここで止まる。
コラムを保存する処理（column_writer / week_column / night_columns / weekly_pipeline / predict_by_race_id）は
すべて保存の直後にこの監査を通し、不合格なら公開を取り下げる。X 投稿の用意（Mac の定時タスク）も合格したものだけ。
方針: 「読めなかったので確かめられなかった」は合格ではなく不合格（図・内ラチの線・レース日 など）。

鬼眼コラム（/predict-v2?raceId=…）で確かめること:
  1. 表示されたコラムが要求したレースのもの（data-race-id）
  2. 本文の印（「◎は6番」「◎6番」どちらの書き方も）が、出てくる全ての箇所でカードの印と同じ。◎は必須
  3. 本文の頭数: 出走頭数を言う表現（「17頭の戦い」「17頭立て」「出走は17頭」など）と、10頭以上の「N頭」がカードの数と同じ
  4. 展開図（data-diagram）: ok なら2枚とも 丸の数・図の印・丸の色（枠）がカードと同じ、
     回り（data-direction）が競馬場と同じ（東京・新潟・中京=左、ほかの中央=右。直線は新潟だけ）、
     テレビの見え方: 場面の直線（スタート地点は race_diagram.START_SIDE で引き直す）ごとに、
     スタンド前=内ラチ上（左回り・直線は左→右、右回りは右→左）、向正面=内ラチ下（左回りは右→左、右回りは左→右）。
     broken（図のデータが壊れている）は不合格
  5. 馬場を「（確定）」と書いてよいのはレース当日だけ。レース日が読めないのに「（確定）」は不合格
  6. 情報元・第三者の名前、語り口に合わない言葉、結果を保証する言い方が無い（column_writer の禁止語と共通）
週中コラム（/column の #race-<race_id> の data-edition=<thu|fri>）で確かめること:
  要求した版の本文について 3・6 に加えて、印（◎○▲△、注＋馬番）と顔つきの話が無いこと
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

VENUES = {'01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
          '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'}
LEFT = {'東京', '新潟', '中京'}
WAKU_FILL = {'#ffffff': 1, '#222222': 2, '#e53935': 3, '#1e5bd8': 4,
             '#fdd835': 5, '#2e9e44': 6, '#f57c00': 7, '#f48fb1': 8}
MARKS = ('◎', '○', '▲', '△', '注')
RAIL_STROKE = '#e8f5e0'
GUARANTEE_NG = ('絶対', '確実', '鉄板', '必ず勝')
# 出走頭数を言う表現（「17頭の戦い」「17頭立て」「17頭が出走」「出走は17頭」「17頭で争う」）
FIELD_AROUND = re.compile(r'出走|頭の戦い|頭立て|頭で争|頭がそろ|頭が揃|頭の争い|フルゲート')
# 頭数でも出走頭数ではないもの（過去の傾向「3着以内15頭のうち」、木曜の「登録は20頭」）
NOT_FIELD = re.compile(r'以内|うち|勝ち馬|以下|以上|人気|過去')


def _ng_words():
    """禁止語は文章を作る側（column_writer）と同じものを使う（片方だけ直して食い違うのを防ぐ）"""
    from column_writer import SOURCE_NG, VOICE_NG
    return tuple(SOURCE_NG) + tuple(VOICE_NG) + GUARANTEE_NG


def _norm(text):
    """全角・半角、大文字・小文字の違いで禁止語をすり抜けないように"""
    return unicodedata.normalize('NFKC', text or '').lower()


def resolve_base(base=None):
    """監査するのは公開中のページ。宛先は明示が必須（黙って localhost などに向かない）"""
    base = base or os.getenv('APP_PUBLIC_URL')
    if not base:
        raise RuntimeError('監査先が決まっていない（--base か APP_PUBLIC_URL を指定）')
    return base.rstrip('/')


def _today():
    return datetime.now(timezone(timedelta(hours=9))).date()


def _get(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, 'lxml')


def _race_date(soup, race_id):
    """レース選択の「10/04　毎日王冠」から日付（年は race_id の先頭4桁）。読めなければ None"""
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
    """本文の印の全ての出現 → [(印, 馬番)]（「◎は6番」「◎6番」「○16番」）"""
    return [(mk, int(n)) for mk, n in re.findall(r'([◎○▲△注])(?:は|\s)*(\d{1,2})番', text)]


def _headcount(text, field, problems):
    """出走頭数を言う表現・10頭以上の「N頭」は field と同じであること"""
    for m in re.finditer(r'(\d{1,2})頭', text):
        n = int(m.group(1))
        before, after = text[max(0, m.start() - 10): m.start()], text[m.end(): m.end() + 6]
        around = before + m.group(0) + after
        if re.search(r'登録', before + after):
            continue                                   # 木曜の登録頭数は出走数と違ってよい
        if NOT_FIELD.search(before[-6:] + after):
            continue
        if (FIELD_AROUND.search(around) or n >= 10) and n != field:
            problems.append(f'本文の「{m.group(0)}」が出走頭数 {field}頭 と違う（…{around}…）')


# 週中コラムで「今回のレースの出走頭数」を言っている表現だけ（近走の「（14頭・芝1200m）」「16頭立ての3着」など
# 過去のレースの頭数は対象にしない）。「出走は17頭」「17頭が出走」「出走頭数17頭」「17頭で争われ」
WEEK_FIELD = re.compile(r'出走(?:頭数)?(?:は|が|予定は)?\s*(\d{1,2})頭|(\d{1,2})頭(?:が出走|で争|がそろ|が揃|の争い|の戦い)')


def _week_headcount(text, field, problems):
    """週中コラムの頭数: 今回の出走頭数を言っている表現だけを確かめる（登録頭数・過去のレースの頭数は見ない）"""
    for m in WEEK_FIELD.finditer(text):
        n = int(m.group(1) or m.group(2))
        around = text[max(0, m.start() - 8): m.end() + 4]
        if '登録' in around or '予定' in around:
            continue                       # 登録頭数・出走予定（木曜の段階）は出走頭数と違ってよい
        if n != field:
            problems.append(f'本文の「{m.group(0)}」が出走頭数 {field}頭 と違う（…{around}…）')


def _words(text, problems):
    t = _norm(text)
    for w in _ng_words():
        if _norm(w) in t:
            problems.append(f'使わない言葉「{w}」がある')


def audit_race_column(race_id, base=None):
    """鬼眼コラムの監査 → 問題のリスト（空なら合格）"""
    base = resolve_base(base)
    problems = []
    soup = _get(f'{base}/predict-v2?raceId={race_id}')
    col = soup.select_one('.column-card')
    if not col:
        return ['鬼眼コラムが表示されていない']
    if col.get('data-race-id') != race_id:
        return [f'表示されたコラムが別のレースのもの（{col.get("data-race-id")}）']
    body = ' '.join(p.get_text() for p in col.select('.column-p'))
    title = (col.select_one('.column-title') or col).get_text()
    cards = _cards(soup)
    if not cards:
        return ['出走馬カードが読めない']
    card_marks = {v['mark']: n for n, v in cards.items() if v['mark'] in MARKS}

    # 2. 印（全ての出現を確かめる）
    found = _text_marks(body)
    for mk, n in found:
        if card_marks.get(mk) != n:
            problems.append(f'本文の{mk}{n}番と、カードの{mk}（{card_marks.get(mk)}番）が違う')
    if '◎' not in {mk for mk, _ in found}:
        problems.append('本文に◎が見つからない')
    for n, name in re.findall(r'(\d{1,2})番([ァ-ヴー]{2,})', body):
        c = cards.get(int(n))
        if not c:
            problems.append(f'本文の{n}番は出走馬にいない')
        elif not (c['name'].startswith(name) or name.startswith(c['name'])):
            problems.append(f'本文の{n}番{name}と、カードの{n}番{c["name"]}が違う')
    # 3. 頭数
    _headcount(body, len(cards), problems)
    # 4. 展開図
    status = col.get('data-diagram')
    venue = VENUES.get(str(race_id)[4:6])
    if status == 'broken':
        problems.append('展開図のデータが壊れている')
    elif status == 'ok':
        svgs = col.select('.diagram svg')
        if [s.get('data-key') for s in svgs] != ['start', 'stretch']:
            problems.append(f'展開図が図1（スタート）・図2（直線）の2枚になっていない（{[s.get("data-key") for s in svgs]}）')
        for i, svg in enumerate(svgs, 1):
            _audit_svg(i, svg, cards, card_marks, venue, problems)
    elif status != 'none':
        problems.append(f'展開図の状態が読めない（{status}）')
    # 5. 馬場の「確定」
    if '確定）' in body:
        rd = _race_date(soup, race_id)
        if rd is None:
            problems.append('レース日が読めないのに馬場を「確定」と書いている')
        elif rd > _today():
            problems.append(f'レース前日以前（{rd}）なのに馬場を「確定」と書いている')
    # 6. 言葉
    _words(title + body, problems)
    return problems


def _audit_svg(i, svg, cards, card_marks, venue, problems):
    horses = svg.select('g.dg-horse')
    if len(horses) != len(cards):
        problems.append(f'図{i}の丸 {len(horses)}頭 と、カード {len(cards)}頭 が違う')
    dmarks = {}
    for g in horses:
        texts = g.find_all('text')
        n = int(texts[0].get_text())
        if len(texts) > 1 and texts[1].get_text() in MARKS:
            if texts[1].get_text() in dmarks:
                problems.append(f'図{i}に{texts[1].get_text()}が2頭いる')
            dmarks[texts[1].get_text()] = n
        fill = (g.find('circle') or {}).get('fill')
        wk = cards.get(n, {}).get('waku')
        if n not in cards:
            problems.append(f'図{i}の{n}番は出走馬にいない')
        elif wk and WAKU_FILL.get(fill) != wk:
            problems.append(f'図{i}の{n}番の丸の色が枠（{wk}枠）と違う')
    if dmarks != card_marks:
        problems.append(f'図{i}の印 {dmarks} と、カードの印 {card_marks} が違う')
    d = svg.get('data-direction')
    if d not in ('右', '左', '直線'):
        problems.append(f'図{i}の回りが分からない（{d}）')
        return
    if venue:
        want = '左' if venue in LEFT else '右'
        if d != want and not (d == '直線' and venue == '新潟'):
            problems.append(f'図{i}の回り「{d}」が{venue}（{want}回り）と違う')
    # テレビ（スタンド）から見た向き。場面がどちらの直線か（data-side）で決まる:
    #   スタンド前（home）… 内ラチは上。左回り・直線は左→右、右回りは右→左
    #   向正面（back）    … 内ラチは下。左回りは右→左、右回りは左→右
    key, side = svg.get('data-key'), svg.get('data-side')
    want_side = 'home' if key == 'stretch' else _expected_start_side(svg.get('data-course'), venue)
    if want_side is None:
        problems.append(f'図{i}のスタート地点が確かめられない（コース {svg.get("data-course")}）')
        return
    if side != want_side:
        problems.append(f'図{i}の場面が{"スタンド前" if side == "home" else "向正面" if side == "back" else side}になっている'
                        f'（{svg.get("data-course")}は{"スタンド前" if want_side == "home" else "向正面"}）')
        return
    rail_top = want_side == 'home'
    want_travel = ('left' if d == '右' else 'right') if rail_top else ('left' if d == '左' else 'right')
    rail_attr = svg.get('data-rail')
    rail = next((l for l in svg.find_all('line') if l.get('stroke') == RAIL_STROKE), None)
    if rail is None:
        problems.append(f'図{i}に内ラチの線が無い')
    elif (float(rail.get('y1')) < 100) != rail_top or rail_attr != ('top' if rail_top else 'bottom'):
        problems.append(f'図{i}の内ラチが{"下" if rail_top else "上"}（テレビの見え方では{"上" if rail_top else "下"}）')
    if svg.get('data-travel') != want_travel:
        problems.append(f'図{i}の進む向き（{svg.get("data-travel")}）が違う（{"右→左" if want_travel == "left" else "左→右"}のはず）')
    goal = svg.select_one('text.dg-goal')
    gt = goal.get_text().strip() if goal else ''
    if not (gt.startswith('◀') if want_travel == 'left' else gt.endswith('▶')):
        problems.append(f'図{i}の進行方向の矢印「{gt}」が違う')
    finish = svg.select_one('line.dg-finish')
    if (key == 'stretch') != (finish is not None):
        problems.append(f'図{i}のゴール板の有無が違う')
    if finish is not None and (float(finish.get('x1')) < 400) != (want_travel == 'left'):
        problems.append(f'図{i}のゴール板が{"左" if float(finish.get("x1")) < 400 else "右"}にある')
    if horses and finish is not None:
        xs = sorted(float(g.find('circle').get('cx')) for g in horses)
        lead = xs[0] if want_travel == 'left' else xs[-1]
        if abs(lead - float(finish.get('x1'))) > 120:
            problems.append(f'図{i}の先頭の馬がゴール板から離れている（向きが逆の可能性）')


def _expected_start_side(course, venue):
    """data-course（例: 東京芝1800 / 京都芝2400(外)）から、スタート地点の直線を表で引き直す"""
    import race_diagram
    m = re.match(r'^(\D+?)(芝|ダ)(\d{3,4})(?:\((外|内)\))?$', course or '')
    if not m or (venue and m.group(1) != venue):
        return None
    return race_diagram.start_side(m.group(1), m.group(2), int(m.group(3)), m.group(4))


def audit_week_column(race_id, edition, base=None):
    """週中コラム（指定した版）の監査 → 問題のリスト（空なら合格）"""
    base = resolve_base(base)
    if edition not in ('thu', 'fri'):
        return [f'週中コラムの版の指定が違う（{edition}）']
    problems = []
    card = _get(f'{base}/column').select_one(f'#race-{race_id}')
    block = card.select_one(f'[data-edition="{edition}"]') if card else None
    if not block:
        return [f'週中コラム（{edition}）が表示されていない']
    body = ' '.join(p.get_text() for p in block.select('.col-p'))
    title = (block.select_one('.col-title') or block).get_text()
    if not body.strip():
        return ['週中コラムの本文が読めない']
    for mk in ('◎', '○', '▲', '△'):
        if mk in body:
            problems.append(f'週中コラムに印「{mk}」がある')
    if re.search(r'注\s*\d{1,2}番', body):
        problems.append('週中コラムに印「注」がある')
    for w in ('顔', '目つき', '眼差し'):
        if w in body:
            problems.append(f'週中コラムに顔の話「{w}」がある')
    cards = _cards(_get(f'{base}/predict-v2?raceId={race_id}'))
    if cards:
        _week_headcount(body, len(cards), problems)
    else:
        problems.append('出走馬カードが読めない（頭数を確かめられない）')
    _words(title + body, problems)
    return problems


def audit(race_id, week_edition=None, base=None):
    """監査を実行し、問題のリストを返す。監査そのものが失敗したら、それも問題として返す（合格にしない）"""
    try:
        return audit_week_column(race_id, week_edition, base) if week_edition else audit_race_column(race_id, base)
    except Exception as e:
        return [f'監査を実行できなかった: {e}']


def take_down(conn, race_id, week_edition):
    cur = conn.cursor()
    if week_edition:
        cur.execute("DELETE FROM week_column WHERE race_id = %s AND edition = %s", (race_id, week_edition))
    else:
        cur.execute("DELETE FROM race_column WHERE race_id = %s", (race_id,))
    conn.commit()
    cur.close()


def enforce(conn, race_id, week_edition, rewrite, log=print):
    """公開したコラムを監査し、不合格なら rewrite() で1回だけ書き直して再監査（rewrite=None なら書き直さない）。
    それでも不合格なら公開を取り下げる（行を消す）。戻り値: (合格したか, 問題のリスト)
    week_edition: 週中コラムなら 'thu' / 'fri'、鬼眼コラムなら None"""
    problems = audit(race_id, week_edition)
    if problems and rewrite:
        log(f"  ⚠️ 監査 不合格 → 書き直して再監査: {' / '.join(problems)}")
        rewrite()
        problems = audit(race_id, week_edition)
    if problems:
        take_down(conn, race_id, week_edition)
        log(f"  ⛔ 監査に通らないため公開を取り下げました: {' / '.join(problems)}")
        return False, problems
    return True, []


def gate_after_write(conn, race_id, week_edition=None, log=print):
    """コラムを保存した処理の最後に、書いた側が自分で呼ぶ関門（書き直しはしない）。
    コラムが公開されていれば監査し、不合格なら取り下げる。戻り値: (合格（またはコラムが無い）なら True, 問題のリスト)"""
    cur = conn.cursor()
    if week_edition:
        cur.execute("SELECT 1 FROM week_column WHERE race_id = %s AND edition = %s", (race_id, week_edition))
    else:
        cur.execute("SELECT 1 FROM race_column WHERE race_id = %s", (race_id,))
    exists = cur.fetchone() is not None
    cur.close()
    if not exists:
        return True, []
    passed, problems = enforce(conn, race_id, week_edition, None, log)
    log("ページ監査: 合格" if passed else "ページ監査: 不合格 → 公開を取り下げ（" + ' / '.join(problems) + "）")
    return passed, problems


def main():
    args = [a for i, a in enumerate(sys.argv[1:], 1)
            if not a.startswith('--') and sys.argv[i - 1] not in ('--base', '--week')]
    if not args:
        print(__doc__)
        sys.exit(2)
    base = sys.argv[sys.argv.index('--base') + 1] if '--base' in sys.argv else None
    edition = sys.argv[sys.argv.index('--week') + 1] if '--week' in sys.argv else None
    if '--week' in sys.argv and edition not in ('thu', 'fri'):
        print('--week には thu か fri を指定')
        sys.exit(2)
    rid = args[0]
    problems = audit(rid, edition, base)
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
