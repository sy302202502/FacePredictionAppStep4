"""
composite_scorer.py
顔面スコア × 当日オッズ の複合スコアを計算して race_specific_result を更新する

【スコアリング方針】
  - 顔スコア: 0〜100点（高いほど勝ち馬顔に近い）
  - オッズ補正:
      1倍台 → 既に市場が評価済み → 複合スコアの上乗せ小
      3〜6倍 → オッズ妥当 → 複合スコアに顔スコアをそのまま反映
      10倍超 → 市場未評価 × 顔スコア高 → 穴馬ボーナス
  - 「顔スコア高 × オッズ高」＝ 最高の狙い目
  - 「顔スコア低 × オッズ低」＝ 人気先行注意

使い方:
  python composite_scorer.py "日本ダービー"
"""

import sys
import os
import math
import psycopg2
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest')
    )

def ensure_column(conn):
    cur = conn.cursor()
    for col, defn in [
        ('composite_score',   'FLOAT'),
        ('win_odds',          'FLOAT'),
        ('popularity',        'INTEGER'),
        ('value_rating',      'VARCHAR(20)'),
        ('composite_comment', 'TEXT'),
    ]:
        cur.execute(f"""
            ALTER TABLE race_specific_result
            ADD COLUMN IF NOT EXISTS {col} {defn}
        """)
    conn.commit()
    cur.close()

# ─── 複合スコア計算 ───────────────────────────────────────
def calc_composite(face_score, odds):
    """
    顔スコア(0〜100) × オッズ補正 → 複合スコア(0〜100)

    【考え方】
    - オッズが高い = 市場が軽視 = 顔スコアが高ければ大きな上乗せ
    - オッズが低い = 市場が評価 = 顔スコアと市場が一致 → 安定
    - log(odds) を使うと非線形な補正が自然な形で入る
    """
    if odds is None or odds <= 0:
        return face_score  # オッズなしはそのまま

    # odds_factor: 1倍台=0.8, 3倍=1.0, 6倍=1.15, 10倍=1.25, 30倍=1.4, 100倍=1.5
    odds_factor = 0.75 + 0.25 * math.log(max(odds, 1.0), 10)
    odds_factor = min(1.5, max(0.7, odds_factor))

    composite = face_score * odds_factor
    return round(min(100.0, max(0.0, composite)), 1)

def value_rating(face_score, odds):
    """穴馬度・注意度ラベルを返す"""
    if odds is None:
        return "データなし"
    if face_score >= 70 and odds >= 10:
        return "★穴馬注目"
    if face_score >= 70 and odds < 4:
        return "本命堅実"
    if face_score >= 60 and 4 <= odds < 10:
        return "対抗候補"
    if face_score < 50 and odds < 3:
        return "⚠人気先行"
    if face_score < 50 and odds >= 10:
        return "評価なし"
    return "普通"

def composite_comment(horse_name, face_score, odds, rating):
    parts = []
    if face_score >= 70:
        parts.append(f"顔面スコアが高く({face_score:.0f}点)勝ち馬顔に近い")
    elif face_score >= 55:
        parts.append(f"顔面スコアは平均的({face_score:.0f}点)")
    else:
        parts.append(f"顔面スコアはやや低め({face_score:.0f}点)")

    if odds:
        if odds < 3:
            parts.append(f"単勝{odds:.1f}倍の1番人気クラスで市場評価も高い")
        elif odds < 8:
            parts.append(f"単勝{odds:.1f}倍で妥当な人気")
        elif odds < 20:
            parts.append(f"単勝{odds:.1f}倍と市場では軽視されている")
        else:
            parts.append(f"単勝{odds:.1f}倍の大穴馬")

    if rating == "★穴馬注目":
        parts.append("→ 顔×オッズのギャップが大きく狙い目")
    elif rating == "⚠人気先行":
        parts.append("→ 人気に比べ顔スコアが低く過大評価の可能性")

    return "　".join(parts)

# ─── メイン ──────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("使い方: python composite_scorer.py \"レース名\"")
        sys.exit(1)

    race_name = sys.argv[1]
    conn = get_conn()
    ensure_column(conn)
    cur = conn.cursor()

    # race_specific_result と race_odds を結合
    cur.execute("""
        SELECT r.id, r.horse_name, r.score, o.win_odds, o.popularity
        FROM race_specific_result r
        LEFT JOIN race_odds o ON o.race_name ILIKE '%%' || r.race_name || '%%'
                              AND o.horse_name = r.horse_name
        WHERE r.race_name = %s
        ORDER BY r.rank_position
    """, (race_name,))
    rows = cur.fetchall()

    if not rows:
        print(f"[エラー] {race_name} の予想データが見つかりません")
        cur.close()
        conn.close()
        sys.exit(1)

    has_odds = any(r[3] is not None for r in rows)
    if not has_odds:
        print(f"[警告] {race_name} のオッズデータがありません")
        print("先に odds_fetcher.py を実行してください")

    print(f"\n=== {race_name} 複合スコア計算 ===")
    results = []
    for row_id, horse_name, face_score, win_odds, popularity in rows:
        comp  = calc_composite(face_score or 50, win_odds)
        rat   = value_rating(face_score or 50, win_odds)
        comm  = composite_comment(horse_name, face_score or 50, win_odds, rat)
        results.append((row_id, horse_name, face_score, win_odds, popularity, comp, rat, comm))

    # 複合スコアでソートして順位を再計算
    results.sort(key=lambda x: x[5], reverse=True)

    print(f"\n{'順位':4} {'馬名':12} {'顔':6} {'オッズ':7} {'複合':6} {'評価':10}")
    print("-" * 55)
    for rank, (row_id, horse_name, face_score, win_odds, pop, comp, rat, comm) in enumerate(results, 1):
        odds_str = f"{win_odds:.1f}倍" if win_odds else "---"
        print(f"{rank:4} {horse_name:12} {face_score or 0:5.1f}点  {odds_str:7} {comp:5.1f}点  {rat}")

    # DBに保存
    for rank, (row_id, horse_name, face_score, win_odds, pop, comp, rat, comm) in enumerate(results, 1):
        cur.execute("""
            UPDATE race_specific_result
            SET composite_score   = %s,
                win_odds          = %s,
                popularity        = %s,
                value_rating      = %s,
                composite_comment = %s
            WHERE id = %s
        """, (comp, win_odds, pop, rat, comm, row_id))

    conn.commit()
    cur.close()
    conn.close()
    print(f"\n→ DBに保存完了。/predict-v2?raceName={race_name} で確認できます")
    print("=== 完了 ===")

if __name__ == '__main__':
    main()
