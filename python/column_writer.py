"""
column_writer.py — 重賞の「鬼眼コラム」を舞鬼法師の語り口で書く

  python3 python/column_writer.py <race_id> [--grade G1] [--force] [--dry-run] [--only-existing]
  --only-existing: すでにコラムがあるレースだけ書き直す（再予想の後に呼ぶ用。重賞判定を持たない経路向け）

【材料】アプリ自前のデータだけを使う（東スポ競馬のデータは規約上、公開する文章には使わない）
  ・当日の馬場（netkeiba確定 or 気象庁予報からの推定）   … stats_prediction.score_detail「当日馬場」
  ・想定ペースと各馬の脚質                               … 同「想定ペース」「脚質」「展開」
  ・枠順（馬番・枠番）                                   … race_entry
  ・鬼眼の印（◎○▲△注）と顔面コメント・統計の根拠        … /predict-v2 と同じ順位付け
【生成】Gemini で文章化 → 検査に通らなければ、テンプレート文章に切り替える
【保存】race_column テーブル（race_id 単位）。材料が前回と同じなら作り直さない
        （当日朝に馬場が確定する・出走馬が変わる などで材料が変われば書き直す）
【条件】枠順（馬番）が確定していないレースは書かない（隊列の話ができないため）
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

import psycopg2
from dotenv import load_dotenv

from llm_client import generate_text
from race_condition import place_from_race_id

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

MARKS = ['◎', '○', '▲', '△', '注']
# /predict-v2 の順位付け（FaceRankingService）と同じ配合。変える場合は両方そろえること
FACE_WEIGHT, STATS_WEIGHT = 0.75, 0.25

PERSONA = """あなたは競馬予想VTuber「舞鬼法師（まいきーほうし／MIKEY MASTER）」として、
重賞レースの展開予想コラムを書く。

【キャラクター】
- 一人称は「僕」。読者への呼びかけは「みんな」
- 熱くてノリのいい配信者。テンポよく、要所で熱量を上げる
- 馬の顔つきから能力を見抜く「鬼眼（きがん）」が売り。決め言葉として「鬼眼」を自然に使う
- 下品な言葉・煽り・他者の悪口は使わない

【守ること（最重要）】
- 書いてよい事実は、渡された「材料」にあるものだけ。材料にない過去の戦績・騎手の話・
  コースの傾向・調教の中身・オッズ・人気などを作らない
- 馬名・馬番・枠番・脚質・馬場・ペースは材料と一字一句一致させる
- 「絶対」「確実」「鉄板」「必ず勝つ」など結果を保証する言い方はしない。馬券は自己判断で、という姿勢
- 一般論として使ってよいのは次の「傾向」だけ。コース形態や当日の馬場状態で逆になることも多いので、
  必ず「〜になりやすい」「〜の可能性がある」と推測の言い方で書き、断定しない:
  内枠の先行馬はロスなく前に付けやすい傾向／外枠の逃げ馬はハナを取るのに脚を使いやすい傾向／
  逃げ・先行馬が多いとペースが速くなり差しが届きやすい傾向／少ないとスローになり前が残りやすい傾向／
  芝の道悪は時計がかかりやすい／ダートの道悪は時計が速くなりやすい
- 材料にない話題（騎手・人気・オッズ・調教・過去のレース名）には触れない
"""

TASK = """以下の「材料」だけを使って、{race}の鬼眼コラムを書いてください。

構成（見出しは付けず、段落で流れを作る。全体で550〜750字）:
1. つかみ（レース名と、みんなへの呼びかけ）
2. 馬場と天気: 当日の馬場状態と、それがどんな馬に向くか
3. 枠順と隊列: 逃げ・先行馬の枠の並びから、ハナを切りそうな馬とスタート後の隊列
4. ペースと展開: 想定ペースと、前有利か差し有利か
5. ◎の推し理由: 鬼眼（顔つき）と統計の両面から
6. 穴馬: 「展開の穴」の馬を、展開が向く理由とともに一言
7. 締め（鬼眼の決め台詞で）

馬名を出すときは必ず「10番ウェイワードアクト」のように馬番を前に付ける。

出力はJSONのみ: {{"title": "30字以内の見出し", "body": "本文（段落は改行2つで区切る）"}}

材料:
{facts}
"""


def notify_discord(text):
    url = os.getenv('DISCORD_WEBHOOK_URL', '').strip()
    if not url:
        return
    try:
        import requests
        requests.post(url, json={'content': text[:1900]}, timeout=10)
    except Exception as e:
        print(f"  [通知] Discord送信に失敗: {e}")


def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'), user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest'),
        connect_timeout=int(os.getenv('PGCONNECT_TIMEOUT', '15')),
        options='-c statement_timeout=60000')


def ensure_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_column (
            race_id    VARCHAR(20) PRIMARY KEY,
            race_name  VARCHAR(200),
            title      VARCHAR(200) NOT NULL,
            body       TEXT NOT NULL,
            generator  VARCHAR(40),
            facts_hash VARCHAR(64),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("ALTER TABLE race_column ADD COLUMN IF NOT EXISTS tweet TEXT")
    conn.commit()
    cur.close()


def _style(detail):
    """「差し（直近6走…）」→「差し」。判定不能は None"""
    m = re.match(r'(逃げ|先行|差し|追込)', detail.get('脚質') or '')
    return m.group(1) if m else None


def _first_sentence(text):
    return (text or '').split('。')[0].strip() or None


def load_facts(conn, race_id, grade=None):
    """コラムの材料（辞書）。書けない条件なら (None, 理由)"""
    cur = conn.cursor()
    cur.execute("""
        SELECT sp.horse_name, re.horse_number, re.post_position, sp.face_score, sp.score,
               sp.score_detail, sp.comment, sp.face_comment,
               re.race_name, re.race_date, re.distance, re.surface
        FROM stats_prediction sp
        JOIN race_entry re ON re.race_id = sp.race_id AND re.horse_id = sp.horse_id
        WHERE sp.race_id = %s
    """, (race_id,))
    rows = cur.fetchall()
    cur.close()
    if not rows:
        return None, '予想データなし'
    # 全頭の馬番がそろうまで書かない。/predict-v2 の順位付けは出走表の全頭が対象なので、
    # 一部の馬を外して書くと画面の◎とコラムの◎が食い違うおそれがある
    if any(r[1] is None for r in rows):
        return None, '枠順（馬番）が未確定'
    if all(r[3] is None for r in rows):
        return None, '顔面分析が未完了'

    horses = []
    for name, num, waku, face, stats, detail_json, comment, face_comment, *_ in rows:
        try:
            detail = json.loads(detail_json) if detail_json else {}
        except ValueError:
            detail = {}
        composite = None if face is None else face * FACE_WEIGHT + (stats if stats is not None else face) * STATS_WEIGHT
        horses.append({
            'name': name, 'num': num, 'waku': waku, 'composite': composite,
            'style': _style(detail), 'detail': detail,
            'stats_comment': comment, 'face_comment': face_comment,
        })
    # 顔面分析済み → 合成スコア降順（同点は馬番順）、未分析は末尾
    horses.sort(key=lambda h: (h['composite'] is None, -(h['composite'] or 0), h['num']))
    for i, h in enumerate(horses):
        h['mark'] = MARKS[i] if i < len(MARKS) and h['composite'] is not None else None

    race_name, race_date, distance, surface = rows[0][8], rows[0][9], rows[0][10], rows[0][11]
    d0 = horses[0]['detail']
    # コラムの肝は馬場と展開。どちらかが分からない（古い予想・取得失敗）なら書かない
    if not d0.get('当日馬場') or not d0.get('想定ペース'):
        return None, '馬場・想定ペースの材料なし（統計予想の再計算待ち）'
    front = sorted([h for h in horses if h['style'] in ('逃げ', '先行')], key=lambda h: h['num'])

    # 展開の穴: 印の外（6番手以下）で、展開補正がプラスのうち統計スコアが最も高い馬
    def pace_plus(h):
        m = re.search(r'([+-]\d+(?:\.\d+)?)pt', h['detail'].get('展開') or '')
        return float(m.group(1)) if m else 0.0
    outside = [h for h in horses if h['mark'] is None and pace_plus(h) > 0]
    dark = max(outside, key=lambda h: (pace_plus(h), h['composite'] or 0), default=None)

    def horse_facts(h):
        return {
            '印': h['mark'], '馬番': h['num'], '枠番': h['waku'], '馬名': h['name'],
            '脚質': h['style'] or '不明',
            '顔面の見立て': _first_sentence(h['face_comment']),
            '統計の根拠': h['stats_comment'],
            '当日馬場への適性': h['detail'].get('馬場状態適性'),
            '距離適性': h['detail'].get('距離適性'),
        }

    roster = {h['num']: h for h in horses}
    facts = {
        'レース': race_name,
        '格付け': grade,
        '開催日': str(race_date),
        '競馬場': place_from_race_id(race_id),
        'コース': f"{surface}{distance}m" if distance else surface,
        '出走頭数': len(horses),
        '当日の馬場': d0.get('当日馬場') or '不明',
        '想定ペース': d0.get('想定ペース') or '不明',
        '逃げ・先行馬（馬番順）': [
            {'馬番': h['num'], '枠番': h['waku'], '馬名': h['name'], '脚質': h['style']} for h in front],
        '鬼眼の印': [horse_facts(h) for h in horses if h['mark']],
        '展開の穴': (dict(horse_facts(dark), **{'展開の見立て': dark['detail'].get('展開')}) if dark else None),
    }
    # 検査用（ハッシュ・LLMには渡さない）: 馬番 → 馬名・印
    facts['_roster'] = {num: {'name': h['name'], 'mark': h['mark']} for num, h in roster.items()}
    return facts, None


def _facts_hash(facts):
    return hashlib.sha256(json.dumps(_public(facts), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


PACES = ('ハイペース', '平均ペース', 'スローペース')
CONDITIONS = ('不良', '稍重', '重', '良')
# 材料に無ければ書いてはいけない話題（創作の温床）
OFF_TOPIC = ('騎手', '鞍上', '人気', 'オッズ', '調教', '追い切り', '前走', '勝ち鞍', '重賞勝ち')


def _public(facts):
    return {k: v for k, v in facts.items() if not k.startswith('_')}


def _valid(col, facts):
    """生成結果の事実検査。問題があれば理由（文字列）、なければ None。
    馬番と馬名・印の組み合わせ、ペース、馬場、材料外の話題を材料と突き合わせる。"""
    if not isinstance(col, dict) or not col.get('title') or not col.get('body'):
        return '形式不正'
    body, title = col['body'], col['title']
    text = title + '\n' + body
    if not 350 <= len(body) <= 1300:
        return f'文字数 {len(body)}'
    top = facts['鬼眼の印'][0]
    if top['馬名'] not in body:
        return '◎の馬名がない'
    return _check_facts(text, facts)


def _check_facts(text, facts):
    """本文・X投稿文に共通の事実検査。問題があれば理由、なければ None。"""
    material = json.dumps(_public(facts), ensure_ascii=False)
    roster = facts['_roster']
    for w in ('絶対', '確実', '鉄板', '必ず勝', '東スポ', '東京スポーツ'):
        if w in text:
            return f'禁止語「{w}」'
    for w in OFF_TOPIC:
        if w in text and w not in material:
            return f'材料にない話題「{w}」'
    # 「10番ウェイワードアクト」: 馬番が出走馬にあり、続く名前がその馬と一致すること
    for m in re.finditer(r'(\d{1,2})番([ァ-ヴー・]+)', text):
        num, name = int(m.group(1)), m.group(2)
        if num not in roster:
            return f'存在しない馬番 {num}'
        if not roster[num]['name'].startswith(name) and not name.startswith(roster[num]['name']):
            return f'馬番と馬名の不一致 {num}番{name}'
    # 「◎10番」「○ウェイワード…」: 印と馬の組み合わせ
    for m in re.finditer(r'([◎○▲△注])\s*(\d{1,2})番', text):
        num = int(m.group(2))
        if num in roster and roster[num]['mark'] != m.group(1):
            return f'印の不一致 {m.group(1)}{num}番'
    # 材料と違うペース・馬場を書いていないか
    pace = next((p for p in PACES if p in facts['想定ペース']), None)
    for p in PACES:
        if p in text and p != pace:
            return f'ペースの不一致「{p}」'
    cond = next((c for c in CONDITIONS if facts['当日の馬場'].startswith(c)), None)
    for c in ('不良', '稍重'):
        if c + '馬場' in text and c != cond:
            return f'馬場の不一致「{c}馬場」'
    if '重馬場' in text and cond != '重' and '稍重馬場' not in text and '不良' not in text:
        return '馬場の不一致「重馬場」'
    if '良馬場' in text and cond != '良':
        return '馬場の不一致「良馬場」'
    return None


def write_with_llm(facts):
    text = generate_text(TASK.format(race=facts['レース'],
                                     facts=json.dumps(_public(facts), ensure_ascii=False, indent=1)),
                         system=PERSONA, json_output=True, temperature=0.9)
    if not text:
        return None, 'LLM応答なし'
    try:
        col = json.loads(text[text.find('{'): text.rfind('}') + 1])
    except ValueError:
        return None, 'JSON解析失敗'
    reason = _valid(col, facts)
    if reason:
        return None, reason
    col['title'] = col['title'].strip()[:60]
    col['body'] = col['body'].strip()
    return col, None


# ------------------------------------------------------------------
# X（旧Twitter）投稿文: コラムを告知用に要約する。投稿はユーザーが手動で行う
# ------------------------------------------------------------------
PUBLIC_URL = os.getenv('APP_PUBLIC_URL', 'http://160.251.251.73:8081')
X_LIMIT = 280       # X の上限（重み付き文字数）
X_URL_WEIGHT = 23   # URL は長さに関係なく23として数えられる

TWEET_TASK = """次の鬼眼コラムを、X（旧Twitter）の告知ポスト用に要約してください。
- 舞鬼法師の語り口（一人称「僕」、熱くノリよく）
- 本文は日本語90〜110字。レース名・◎の馬番と馬名・展開の見どころを入れる
- 馬名を出すときは「10番ウェイワードアクト」のように馬番を付ける
- コラムに書かれていない事実は書かない。「絶対」「確実」など断定しない
- ハッシュタグとURLは付けない（後でこちらで付ける）
出力はJSONのみ: {{"text": "本文"}}

コラム:
{column}
"""


def x_weight(text):
    """X の文字数の数え方（日本語などは2、半角英数記号は1、URLは23）"""
    n = 0
    for token in re.split(r'(https?://\S+)', text):
        if token.startswith('http'):
            n += X_URL_WEIGHT
        else:
            n += sum(1 if ord(c) < 0x1100 else 2 for c in token)
    return n


def build_tweet(text, facts, race_id, race_tag=True):
    tags = '#鬼眼競馬' + (' #' + re.sub(r'[^\w]', '', facts['レース']) if race_tag else '')
    return f"{text.strip()}\n{tags}\n{PUBLIC_URL}/predict-v2?raceId={race_id}"


def write_tweet(col, facts, race_id):
    """(投稿文, 生成方法)。AI が検査に通らなければ定型文。"""
    out = generate_text(TWEET_TASK.format(column=col['body']), system=PERSONA,
                        json_output=True, temperature=0.8, max_tokens=2048)
    try:
        text = json.loads(out[out.find('{'): out.rfind('}') + 1])['text'] if out else None
    except (ValueError, KeyError, TypeError):
        text = None
    if text:
        tweet = build_tweet(text, facts, race_id)
        top = facts['鬼眼の印'][0]
        if (x_weight(tweet) <= X_LIMIT and top['馬名'] in text
                and not _check_facts(text, facts)):
            return tweet, 'gemini'
    top = facts['鬼眼の印'][0]
    pace = facts['想定ペース'].split('（')[0]
    dark = facts['展開の穴']
    head = f"【鬼眼コラム】{facts['レース']}の僕の◎は{top['馬番']}番{top['馬名']}！"
    # 長い場合は 穴馬 → ペース の順に削って上限に収める
    candidates = [
        head + f"想定は{pace}。" + (f"展開の穴は{dark['馬番']}番{dark['馬名']}。" if dark else '') + "続きはこちら👇",
        head + f"想定は{pace}。続きはこちら👇",
        head + "続きはこちら👇",
    ]
    # 長い場合は 穴馬 → ペース → レース名のハッシュタグ の順に削る。URL は必ず残す
    for race_tag in (True, False):
        for text in candidates:
            tweet = build_tweet(text, facts, race_id, race_tag)
            if x_weight(tweet) <= X_LIMIT:
                return tweet, 'template'
    # それでも超える（レース名・馬名が極端に長い）ときは本文を縮める
    text = head
    while text and x_weight(build_tweet(text + '…', facts, race_id, False)) > X_LIMIT:
        text = text[:-1]
    return build_tweet(text + '…', facts, race_id, False), 'template'


def write_template(facts):
    """LLM が使えないときの定型文（舞鬼法師の語り口）。材料の範囲だけで組み立てる。"""
    marks = facts['鬼眼の印']
    top = marks[0]
    front = facts['逃げ・先行馬（馬番順）']
    nige = [h for h in front if h['脚質'] == '逃げ']
    paras = [f"みんな、{facts['レース']}の鬼眼コラムいくよ！ {facts['競馬場'] or ''}{facts['コース']}、"
             f"{facts['出走頭数']}頭の戦いだ。"]
    paras.append(f"馬場は{facts['当日の馬場']}。僕の鬼眼で、この条件を味方にできる馬を探していくよ。")
    def label(h):
        return str(h['馬番']) + '番' + h['馬名']

    if nige:
        paras.append("逃げ候補は" + '、'.join(label(h) for h in nige) + "。"
                     + ("誰がハナを取るのか、スタート直後の先行争いが最初の見どころだね。"
                        if len(nige) >= 2 else "すんなりハナを取れるかがカギになりそうだ。"))
    elif front:
        paras.append("はっきりした逃げ馬はいなくて、先行勢の" + '、'.join(label(h) for h in front[:3])
                     + "が隊列を作る形になりそう。")
    paras.append(f"想定ペースは{facts['想定ペース']}。この流れが結果を左右しそうだ！")
    reason = top['顔面の見立て'] or '顔つきに勝負気配'
    paras.append(f"僕の◎は{top['馬番']}番{top['馬名']}！ {reason}。"
                 + (f"データ面でも{top['統計の根拠']}。" if top['統計の根拠'] else ''))
    if len(marks) >= 3:
        paras.append("相手は" + '、'.join(f"{m['印']}{m['馬番']}番{m['馬名']}" for m in marks[1:]) + "。")
    dark = facts['展開の穴']
    if dark:
        paras.append(f"穴で気になるのは{dark['馬番']}番{dark['馬名']}。{dark['脚質']}の脚質で、"
                     f"{facts['想定ペース'].split('（')[0]}なら展開が向く可能性がある一頭だ。")
    paras.append("最後は自分の目で決めるのが一番。鬼眼の答え合わせは、レースのあとでね！")
    return {'title': f"{facts['レース']} 鬼眼コラム", 'body': '\n\n'.join(paras)}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        print(__doc__)
        sys.exit(2)
    race_id = args[0]
    grade = sys.argv[sys.argv.index('--grade') + 1] if '--grade' in sys.argv else None
    force, dry = '--force' in sys.argv, '--dry-run' in sys.argv

    conn = get_conn()
    ensure_table(conn)
    if '--only-existing' in sys.argv:
        cur0 = conn.cursor()
        cur0.execute("SELECT 1 FROM race_column WHERE race_id = %s", (race_id,))
        exists = cur0.fetchone()
        cur0.close()
        if not exists:
            print("コラムの無いレース → 対象外")
            return
    facts, why = load_facts(conn, race_id, grade)
    cur = conn.cursor()
    if not facts:
        # 材料が不正・不足になったら、古い材料で書いたコラムを公開し続けない
        if not dry:
            cur.execute("DELETE FROM race_column WHERE race_id = %s", (race_id,))
            if cur.rowcount:
                print("  材料が使えなくなったため既存のコラムを取り下げました")
            conn.commit()
        print(f"コラムを書かない: {why}")
        print(f"RESULT:{json.dumps({'success': True, 'skipped': why}, ensure_ascii=False)}")
        return
    h = _facts_hash(facts)
    cur.execute("SELECT facts_hash, generator, tweet FROM race_column WHERE race_id = %s", (race_id,))
    row = cur.fetchone()
    same = bool(row) and row[0] == h
    # X投稿案の機能より前に書いたコラムには投稿案が無い → 本文はそのままで投稿案だけ作る
    if same and row[1] != 'template' and not force and row[2] is None and not dry:
        cur.execute("SELECT title, body FROM race_column WHERE race_id = %s", (race_id,))
        title, body = cur.fetchone()
        tweet, tweet_gen = write_tweet({'title': title, 'body': body}, facts, race_id)
        cur.execute("UPDATE race_column SET tweet = %s WHERE race_id = %s", (tweet, race_id))
        conn.commit()
        print(f"既存コラムにX投稿案を追加（{tweet_gen}）")
        notify_discord(f"📝 **X投稿案**: {facts['レース']}\n```\n{tweet}\n```")
        print(f"RESULT:{json.dumps({'success': True, 'tweet_added': True})}")
        return
    # 材料が同じでも、前回がテンプレート（AIの一時失敗）なら AI で書き直しを試みる
    if same and row[1] != 'template' and not force:
        print("材料に変化なし → 既存のコラムを維持")
        print(f"RESULT:{json.dumps({'success': True, 'skipped': 'unchanged'})}")
        return

    col, reason = write_with_llm(facts)
    generator = 'gemini'
    if not col:
        if same:
            print(f"  AI文章化に失敗（{reason}）→ 既存のコラムを維持")
            print(f"RESULT:{json.dumps({'success': True, 'skipped': 'llm_failed'})}")
            return
        print(f"  AI文章化を使わずテンプレートで作成（理由: {reason}）")
        col, generator = write_template(facts), 'template'

    print(f"\n【{col['title']}】（{generator}・{len(col['body'])}字）\n{col['body']}\n")
    tweet, tweet_gen = write_tweet(col, facts, race_id)
    print(f"X投稿案（{tweet_gen}・{x_weight(tweet)}/{X_LIMIT}）:\n{tweet}\n")
    if not dry:
        cur.execute("""
            INSERT INTO race_column (race_id, race_name, title, body, generator, facts_hash, tweet, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (race_id) DO UPDATE
              SET race_name = EXCLUDED.race_name, title = EXCLUDED.title, body = EXCLUDED.body,
                  generator = EXCLUDED.generator, facts_hash = EXCLUDED.facts_hash,
                  tweet = EXCLUDED.tweet, updated_at = NOW()
        """, (race_id, facts['レース'], col['title'], col['body'], generator, h, tweet))
        conn.commit()
        notify_discord(f"📝 **鬼眼コラムを{'更新' if row else '公開'}**: {facts['レース']}\n"
                       f"X投稿案（コピーして使ってください）:\n```\n{tweet}\n```")
    cur.close()
    conn.close()
    print(f"RESULT:{json.dumps({'success': True, 'generator': generator}, ensure_ascii=False)}")


if __name__ == '__main__':
    main()
