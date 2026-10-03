"""
column_review.py — 公開前のコラムを AI にもう一度読ませて、誤解を招く書き方を見つける（二重チェック）

各コラムの検査（column_writer._valid / week_column.check）は、数字・馬名・禁止語など
機械的に確かめられることを見る。ここでは、それでは拾えない「読み手が誤解する書き方」を見る:
  ・材料に無い事実や数字が書かれていないか
  ・前走と2走前以前など、別の事実を並べて取り違えさせていないか
  ・「同レース」「その馬」など指す先があいまいで、別のものと読めないか
  ・枠の内・中・外（材料の「枠の位置」）と違う書き方をしていないか
  ・材料の数字の意味を取り違えていないか（例: ±200m の範囲の勝利を「この距離」と書く）
問題があれば、その指摘を添えて書き直させる（write_* 側で最大2回）。
"""
from __future__ import annotations

import json

from llm_client import generate_text

REVIEW_TASK = """あなたは競馬コラムの校閲者です。次の「コラム」を「材料」と照らし合わせ、
読み手が事実を誤解するおそれのある箇所だけを指摘してください。文体の好みや言い回しの上手下手は指摘しない。

見る点:
1. 材料に無い事実・数字・肩書きが書かれている
2. 別の事実を並べて取り違えさせている（例: 前走の話の直後に2走前以前のレースを書き、それが前走だと読める）
3. 「同レース」「その馬」「このレース」などの指す先があいまいで、別のものと読める
4. 馬の内・外の書き方が材料の「枠の位置」（内・中・外）と食い違う
5. 材料の数字の意味を取り違えている（例: 「芝1600〜2000mで2勝」を今回の距離ちょうどの勝利のように書く）
6. 結果を保証する言い方（絶対・確実 など）
{extra}

出力はJSONのみ: {{"ok": true または false, "problems": ["問題の箇所と理由を1文で", ...]}}
問題が無ければ {{"ok": true, "problems": []}}

材料:
{facts}

コラム:
{column}
"""


def review(column_text, public_facts, extra=''):
    """AI による校閲。(問題のリスト, 実行できたか) を返す。
    AI が使えないとき（応答なし・解析不能）は ([], False) — 呼び出し側は機械的な検査の結果だけで判断する"""
    text = generate_text(REVIEW_TASK.format(extra=extra,
                                            facts=json.dumps(public_facts, ensure_ascii=False, indent=1),
                                            column=column_text),
                         json_output=True, temperature=0.1)
    if not text:
        return [], False
    try:
        r = json.loads(text[text.find('{'): text.rfind('}') + 1])
    except ValueError:
        return [], False
    if r.get('ok') is True or not r.get('problems'):
        return [], True
    return [str(p)[:200] for p in r['problems']][:5], True


def feedback(problems):
    """書き直しの指示に添える文"""
    return ("\n\n前回の原稿には次の問題がありました。これらを直した原稿を書いてください:\n"
            + '\n'.join(f"- {p}" for p in problems))
