"""
week_column.py — 木曜・金曜に出す重賞の「週中コラム」を舞鬼法師の語り口で書く

  python3 python/week_column.py <race_id> [--grade G2] [--edition thu|fri] [--force] [--dry-run]
  --edition を省くと実行した曜日で決める（木曜=thu、金曜=fri、それ以外は書かない）

【材料】事実だけ。顔面分析・鬼眼の印は使わない（予想画面と土日の鬼眼コラムの役目）
  ・レースの基本（コース・距離・開催日・頭数・出走が確定しているか）
  ・データ上の有力馬（統計スコア上位）の近走の事実 … stats_prediction.recent（race_facts.horse_recent）
  ・過去の同じレースの傾向 … race_facts.past_trends（過去5回の結果。結果ページは1レース1回だけ読んで保存）
【生成】Gemini で文章化 → 事実の検査（馬名・数字・禁止語）に通らなければテンプレート文章に切り替える
【保存】week_column テーブル（race_id × 版）。材料が前回と同じなら作り直さない
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone

from column_writer import get_conn, VOICE, VOICE_NG, MAX_EXCLAIM
from llm_client import generate_text
from race_condition import place_from_race_id
import race_facts

TOP_HORSES = 5
EDITIONS = {'thu': '木曜版', 'fri': '金曜版'}
WEEKDAYS = '月火水木金土日'

PERSONA = """あなたは競馬予想VTuber「舞鬼法師（まいきーほうし／MIKEY MASTER）」として、
週末の重賞に向けた短い「週中コラム」を書く。

【語り口】
""" + VOICE + """

【守ること（最重要）】
- 書いてよい事実は、渡された「材料」にあるものだけ。材料にない戦績・騎手・調教・オッズ・枠順・血統を作らない
- 馬名・着順・人気・頭数・年・距離などの数字は、材料と一字一句一致させる
- 馬の顔つき・顔面分析・鬼眼の印（◎○▲など）には一切触れない。このコラムは事実だけで書く
- 「絶対」「確実」「鉄板」「必ず勝つ」など結果を保証する言い方はしない
- 過去の傾向から言えることは「〜が多い」「〜の可能性がある」と書き、断定しない
"""

TASK = """以下の「材料」だけを使って、{race}の週中コラム（{edition}）を書いてください。

構成（見出しは付けず、段落で流れを作る。全体で400〜600字）:
1. つかみ（レース名とコース。「段階」に合わせて、出走予定の段階か出走確定かを正しく伝える）
2. 過去の同じレースの傾向（材料の数字を2〜3個使い、そこから言えることを推測の言い方で）
3. データ上の有力馬の近走の事実（2〜3頭。近走の着順・重賞実績・同じ条件の成績など、材料の事実で）
4. 締め（ここは熱量を上げてよい。週末が楽しみという一言と、「レース当日の鬼眼コラムでは枠順をふまえた展開図も描く」という予告）

馬名は材料の表記どおりに書く（馬番は書かない）。
「前走」は材料の「前走」の1走だけを指す。2走前・3走前のレースに触れるときは「2走前の〇〇」のように必ず区別して書き、
前走の話と同じ文に並べない。海外・地方のレースは材料の（海外）（地方）の表記を添える。
過去のレースは必ずレース名で書く。「同レース」「そのレース」「同じレース」のように指す先があいまいな言い方はしない。

出力はJSONのみ: {{"title": "30字以内の見出し", "body": "本文（段落は改行2つで区切る）"}}

材料:
{facts}
"""

# 本文に出てよいカタカナ語（馬名・レース名以外）。これ以外のカタカナ語が材料に無ければ作り話とみなす
KATAKANA_OK = {
    'コース', 'レース', 'ペース', 'スタート', 'ゴール', 'ハナ', 'スピード', 'スタミナ', 'データ', 'ポイント',
    'チェック', 'ファン', 'タイム', 'ラスト', 'ステップ', 'ローテーション', 'トライアル', 'メンバー', 'コラム',
    'ハイペース', 'スローペース', 'レベル', 'チャンス', 'パターン', 'ベテラン', 'エース', 'ライバル', 'ドラマ',
    'ワクワク', 'ドキドキ', 'テンション', 'インパクト', 'ゲート', 'カーブ', 'コーナー', 'ホーム', 'ストレッチ',
    'リピーター', 'シーズン', 'スター', 'ヒント', 'ヒーロー', 'ファイナル', 'ステージ', 'バトル', 'マイル',
    'クラシック', 'ダート', 'ターフ', 'グランプリ', 'ジャンプ', 'ポジション', 'スパート', 'キャリア', 'トップ',
    'ゼロ', 'セオリー', 'プラス', 'マイナス', 'ムード', 'リズム', 'ベスト', 'ラップ', 'ゴールイン',
    'デビュー', 'ルーキー', 'ホープ', 'フレッシュ', 'パワー', 'センス', 'ポテンシャル', 'イチオシ', 'ニュース',
    'ルール', 'サプライズ', 'ダークホース', 'ストーリー', 'キャラ', 'ハイレベル', 'ペースアップ', 'スムーズ',
    'ハンデ', 'コンディション', 'ベテラン', 'ブランク', 'ロングスパート', 'ゴール前', 'フィニッシュ', 'ラストスパート',
}
BANNED = ('絶対', '確実', '鉄板', '必ず勝', '東スポ', '東京スポーツ', '顔', '眼差し', '目つき', '◎', '○', '▲', '△') + VOICE_NG
OFF_TOPIC = ('騎手', '鞍上', 'オッズ', '調教', '追い切り', '血統', '父', '母')
NUM_UNIT = re.compile(r'(?<![\d.])(\d+)\s*(番人気|着|勝|頭|年|枠|週|戦|回|m)')


def ensure_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS week_column (
            race_id    VARCHAR(20) NOT NULL,
            edition    VARCHAR(8)  NOT NULL,
            race_name  VARCHAR(200),
            race_date  DATE,
            grade      VARCHAR(8),
            title      VARCHAR(200) NOT NULL,
            body       TEXT NOT NULL,
            generator  VARCHAR(40),
            facts_hash VARCHAR(64),
            updated_at TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'Asia/Tokyo'),
            PRIMARY KEY (race_id, edition)
        )
    """)
    conn.commit()
    cur.close()


def today_jst():
    return datetime.now(timezone(timedelta(hours=9))).date()


def load_facts(conn, race_id, grade, edition):
    """コラムの材料（辞書）。書けない条件なら (None, 理由)"""
    cur = conn.cursor()
    cur.execute("""
        SELECT re.race_name, re.race_date, re.distance, re.surface, sp.horse_name, sp.score, sp.recent, re.horse_id
        FROM race_entry re
        LEFT JOIN stats_prediction sp ON sp.race_id = re.race_id AND sp.horse_id = re.horse_id
        WHERE re.race_id = %s
    """, (race_id,))
    rows = cur.fetchall()
    cur.close()
    if not rows:
        return None, '出走馬データなし'
    race_name, race_date, distance, surface = rows[0][:4]
    scored = [r for r in rows if r[5] is not None]
    if not scored:
        return None, '統計予想なし'
    with_recent = [r for r in scored if r[6]]
    if len(with_recent) < sum(1 for r in scored if r[7]) * 0.8:     # 分母は成績を取れる馬（horse_id あり）
        return None, '近走の事実が未保存（統計予想の再計算待ち）'

    top = sorted(with_recent, key=lambda r: -r[5])[:TOP_HORSES]
    horses = []
    for r in top:
        rec = json.loads(r[6])
        horses.append({'馬名': r[4], '事実': race_facts.horse_lines(rec, race_date),
                       # 検査用（材料には出さない）: 近走の レース名（格付けの括弧を除く）と着順
                       '_runs': [(re.sub(r'\(.*?\)', '', x['race']), x['rank']) for x in rec['runs']]})
    venue = place_from_race_id(race_id)
    trends = race_facts.past_trends(conn, race_name, race_date, venue, surface, distance)
    stage = ('出走予定馬（特別登録）の段階。出走はまだ確定していない' if edition == 'thu'
             else '出走馬が確定した段階')
    facts = {
        'レース': race_name,
        '格付け': grade,
        '開催日': f"{race_date.month}月{race_date.day}日（{WEEKDAYS[race_date.weekday()]}）",
        '競馬場': venue,
        'コース': f"{surface}{distance}m" if distance else surface,
        '段階': stage,
        ('登録頭数' if edition == 'thu' else '出走頭数'): f"{len(rows)}頭",
        'データ上の有力馬（アプリの統計スコア上位。近走成績・距離・馬場・調教などの集計）': horses,
        '過去の同じレース': trends or '記録なし',
    }
    facts['_roster'] = [r[4] for r in rows]
    facts['_race_date'] = str(race_date)
    return facts, None


def _public(facts):
    """LLM・ハッシュに渡す材料（'_' で始まる検査用の項目は、入れ子の中も含めて除く）"""
    def strip(v):
        if isinstance(v, dict):
            return {k: strip(x) for k, x in v.items() if not k.startswith('_')}
        if isinstance(v, list):
            return [strip(x) for x in v]
        return v
    return strip(facts)


def _facts_hash(facts):
    return hashlib.sha256(json.dumps(_public(facts), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def tokens(text):
    """「8番人気」「11着」「2勝」などの 数字＋単位 の集合（数字は前後の数字とつながらない完全一致）"""
    return {m.group(1) + m.group(2) for m in NUM_UNIT.finditer(text)}


def _horse_clauses(text, roster):
    """本文を「どの馬について書いた部分か」に分ける → [(馬名 or None, 部分)]。
    文の中に馬名が出たら、そこから次の馬名までをその馬の部分とする。馬名の無い文は、
    同じ段落で直前に名前が出た馬の続きとして扱う"""
    out = []
    names = sorted(roster, key=len, reverse=True)
    for para in text.split('\n'):
        current = None
        for sent in re.split(r'(?<=[。！？])', para):
            hits = sorted({(m.start(), n) for n in names for m in re.finditer(re.escape(n), sent)})
            # 長い名前に含まれる短い名前の一致は捨てる
            hits = [(i, n) for i, n in hits if not any(j <= i < j + len(m) and m != n for j, m in hits)]
            pos = 0
            for i, n in hits:
                if sent[pos:i].strip():
                    out.append((current, sent[pos:i]))
                current, pos = n, i
            if sent[pos:].strip():
                out.append((current, sent[pos:]))
    return out


def check(col, facts):
    """生成結果の事実検査。問題があれば理由、なければ None。
    自由な文章の事実を完全に確かめることはできないため、確かめられる部分（数字・馬名・着順の対応・
    カタカナ語・禁止語）は厳しく見て、少しでも合わなければテンプレート文章にする"""
    if not isinstance(col, dict) or not col.get('title') or not col.get('body'):
        return '形式不正'
    body, text = col['body'], col['title'] + '\n' + col['body']
    if not 350 <= len(body) <= 900:
        return f'文字数 {len(body)}'
    if body.count('！') + body.count('!') > MAX_EXCLAIM:
        return '「！」が多い（語り口）'
    for w in ('同レース', 'そのレース', '同じレースに', '同競走'):
        if w in text:
            return f'指す先があいまいな言い方「{w}」'
    material = json.dumps(_public(facts), ensure_ascii=False)
    for w in BANNED:
        if w in text:
            return f'禁止語「{w}」'
    for w in OFF_TOPIC:
        if w in text and w not in material:
            return f'材料にない話題「{w}」'
    allowed = tokens(material)
    for t in tokens(text):
        if t not in allowed:
            return f'材料にない数字「{t}」'
    # 馬について書いた部分の数字は、その馬の事実にあるものだけ。着順はレース名（または「前走」）と組で照合
    hs = {h['馬名']: h for h in facts['データ上の有力馬（アプリの統計スコア上位。近走成績・距離・馬場・調教などの集計）']}
    for name, part in _horse_clauses(text, facts['_roster']):
        if not name:
            continue
        h = hs.get(name)
        if not h:
            if tokens(part):
                return f'材料に事実の無い馬「{name}」の数字'
            continue
        own = tokens(' '.join(h['事実']) + facts['コース'])
        for t in tokens(part):
            if t not in own:
                return f"{name}の事実にない数字「{t}」"
        runs = h.get('_runs', [])
        # 「前走から18週の休み明けで、2/15の共同通信杯を1着」のように、前走の話に2走前以前のレースを
        # 並べると、そのレースが前走だと読めてしまう。前走に触れた部分には前走のレース名以外を出さない
        if '前走' in part and runs:
            older = [r for r, _ in runs[1:] if r and r in part and r != runs[0][0]]
            if older and runs[0][0] not in part:
                return f"{name}の前走の話に2走前以前の「{older[0]}」が混ざっている"
        # 着順は、同じ句（読点までの区切り）にあるレース名（前でも後でも、近いほう）か「前走」と組で照合
        for seg in re.split(r'[、，,]', part):
            for m in re.finditer(r'(?<![\d.])(\d+)着(?!以内)', seg):
                near = [(abs(i - m.start()), r, k) for r, k in runs if r
                        for i in [x.start() for x in re.finditer(re.escape(r), seg)]]
                if near:
                    _, race, rank = min(near)
                    if int(m.group(1)) != rank:
                        return f"{name}の{race}の着順が違う（{m.group(1)}着）"
                elif '前走' in seg and runs and int(m.group(1)) != runs[0][1]:
                    return f"{name}の前走の着順が違う（{m.group(1)}着）"
    # カタカナ語は 材料にある（馬名・レース名）か、一般語のリストにあるものだけ
    for w in re.findall(r'[ァ-ヴー]{3,}', text):
        if w not in material and w not in KATAKANA_OK and not any(w in k or k in w for k in KATAKANA_OK):
            return f'材料にないカタカナ語「{w}」'
    return None


def write_with_llm(facts, edition):
    text = generate_text(TASK.format(race=facts['レース'], edition=EDITIONS[edition],
                                     facts=json.dumps(_public(facts), ensure_ascii=False, indent=1)),
                         system=PERSONA, json_output=True, temperature=0.8)
    if not text:
        return None, 'LLM応答なし'
    try:
        col = json.loads(text[text.find('{'): text.rfind('}') + 1])
    except ValueError:
        return None, 'JSON解析失敗'
    reason = check(col, facts)
    if reason:
        return None, reason
    return {'title': col['title'].strip()[:60], 'body': col['body'].strip()}, None


def write_template(facts, edition):
    """AI が使えない・検査に通らないときの文章（材料をそのまま並べる）"""
    name = facts['レース']
    p = [f"みんな、{facts['開催日']}は{facts['競馬場']}{facts['コース']}の{name}です。"
         f"今は{facts['段階'].split('。')[0]}です。"]
    t = facts['過去の同じレース']
    if isinstance(t, dict):
        agg = [t[k] for k in ('1番人気の成績', '人気', '脚質') if t.get(k)]
        if agg:
            p.append(f"まずは{t.get('集計の対象', t['対象'])}の傾向から見ていきましょう。" + '。'.join(agg) +
                     "。この数字が今年どう出るか、注目したいところです。")
        else:
            p.append(f"{t['対象']}の勝ち馬は、{'、'.join(t['年ごとの勝ち馬'])}です。")
    hs = facts['データ上の有力馬（アプリの統計スコア上位。近走成績・距離・馬場・調教などの集計）'][:3]
    if hs:
        lines = []
        for h in hs:
            if not h['事実']:
                continue
            last = h['事実'][0].replace('近走: ', '').split(' / ')[0].replace('前走 ', '', 1)
            same = next((x for x in h['事実'] if x.endswith('回') and 'の成績' in x), None)
            lines.append(f"{h['馬名']}は前走が{last}" + (f"、{same.replace('の成績: ', 'は')}" if same else ''))
        p.append("データ上の有力馬の近走もチェックしておきましょう。" + '。'.join(f"{x}です" for x in lines) + '。')
    p.append("レース当日の鬼眼コラムでは、枠順をふまえた展開図も描いていきます。週末が楽しみです！")
    return {'title': f"{name} {EDITIONS[edition]}・過去の傾向と有力馬の近走", 'body': '\n\n'.join(p)}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        print(__doc__)
        sys.exit(2)
    race_id = args[0]
    grade = sys.argv[sys.argv.index('--grade') + 1] if '--grade' in sys.argv else None
    edition = sys.argv[sys.argv.index('--edition') + 1] if '--edition' in sys.argv else \
        {3: 'thu', 4: 'fri'}.get(today_jst().weekday())
    force, dry = '--force' in sys.argv, '--dry-run' in sys.argv
    if edition not in EDITIONS:
        print("週中コラムは木曜・金曜だけ書く（--edition で指定可）")
        print(f"RESULT:{json.dumps({'success': True, 'skipped': 'not_weekday'})}")
        return

    conn = get_conn()
    ensure_table(conn)
    facts, why = load_facts(conn, race_id, grade, edition)
    if not facts:
        print(f"週中コラムを書かない: {why}")
        print(f"RESULT:{json.dumps({'success': True, 'skipped': why}, ensure_ascii=False)}")
        conn.close()
        return
    h = _facts_hash(facts)
    cur = conn.cursor()
    cur.execute("SELECT facts_hash, generator FROM week_column WHERE race_id = %s AND edition = %s", (race_id, edition))
    row = cur.fetchone()
    if row and row[0] == h and row[1] != 'template' and not force:
        print("材料に変化なし → 既存の週中コラムを維持")
        print(f"RESULT:{json.dumps({'success': True, 'skipped': 'unchanged'})}")
        conn.close()
        return

    col, reason = write_with_llm(facts, edition)
    generator = 'gemini'
    if not col:
        # 材料が同じで既存が AI の文章なら残す。既存がテンプレートなら、語り口などの変更を反映するため作り直す
        if row and row[0] == h and row[1] != 'template':
            print(f"  AI文章化に失敗（{reason}）→ 既存の週中コラムを維持")
            print(f"RESULT:{json.dumps({'success': True, 'skipped': 'llm_failed'})}")
            conn.close()
            return
        print(f"  AI文章化を使わずテンプレートで作成（理由: {reason}）")
        col, generator = write_template(facts, edition), 'template'

    print(f"\n【{col['title']}】（{generator}・{len(col['body'])}字）\n{col['body']}\n")
    if not dry:
        cur.execute("""
            INSERT INTO week_column (race_id, edition, race_name, race_date, grade, title, body, generator, facts_hash, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW() AT TIME ZONE 'Asia/Tokyo')
            ON CONFLICT (race_id, edition) DO UPDATE
              SET race_name = EXCLUDED.race_name, race_date = EXCLUDED.race_date, grade = EXCLUDED.grade,
                  title = EXCLUDED.title, body = EXCLUDED.body, generator = EXCLUDED.generator,
                  facts_hash = EXCLUDED.facts_hash, updated_at = NOW() AT TIME ZONE 'Asia/Tokyo'
        """, (race_id, edition, facts['レース'], facts['_race_date'], grade, col['title'], col['body'], generator, h))
        conn.commit()
    cur.close()
    conn.close()
    print(f"RESULT:{json.dumps({'success': True, 'generator': generator})}")


if __name__ == '__main__':
    main()
