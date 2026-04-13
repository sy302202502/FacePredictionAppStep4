"""
stats_predictor.py  ― APIなし・統計ベース予想

netkeiba から各馬の過去成績をスクレイピングし、以下の指標でスコアリング。
Claude Vision API は一切使用しない。

スコア要素:
  1. 直近5走平均着順 (30pt)  ← 低いほど良い
  2. G1/G2 好走実績 (20pt)
  3. 同距離±200m 勝率 (20pt)
  4. 芝/ダート 適性 (15pt)
  5. 重馬場適性 (本日の馬場状態に応じて加点) (15pt)

使い方:
  python stats_predictor.py 大阪杯
  python stats_predictor.py 大阪杯 --dry-run  # DB保存なし
"""

import sys, os, re, time, json
import requests
import psycopg2
from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

# ----------------------------------------------------------------
# DB
# ----------------------------------------------------------------
def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST','localhost'), port=os.getenv('DB_PORT','5432'),
        dbname=os.getenv('DB_NAME','faceapp'), user=os.getenv('DB_USER','postgres'),
        password=os.getenv('DB_PASSWORD','postgrestest')
    )

def ensure_stats_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stats_prediction (
            id           SERIAL PRIMARY KEY,
            race_name    VARCHAR(200),
            horse_name   VARCHAR(100),
            horse_id     VARCHAR(20),
            rank_position INTEGER,
            score        FLOAT,
            score_detail TEXT,
            comment      TEXT,
            created_at   TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()

# ----------------------------------------------------------------
# 出走馬を取得
# ----------------------------------------------------------------
def get_entries(conn, race_name):
    cur = conn.cursor()
    cur.execute("""
        SELECT horse_name, horse_id, horse_number, jockey_name,
               distance, surface, race_date
        FROM race_entry
        WHERE race_name = %s
        ORDER BY horse_number
    """, (race_name,))
    rows = cur.fetchall()
    cur.close()
    return rows

# ----------------------------------------------------------------
# 馬の過去成績スクレイピング
# ----------------------------------------------------------------
def fetch_horse_results(horse_id, horse_name):
    """直近20走を取得"""
    url = f'https://db.netkeiba.com/horse/result/{horse_id}/'
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        text = r.content.decode('EUC-JP', errors='replace')
        soup = BeautifulSoup(text, 'lxml')
        table = soup.find('table', class_='db_h_race_results')
        if not table:
            return []
        results = []
        for row in table.find_all('tr')[1:21]:  # 直近20走
            cols = [td.text.strip() for td in row.find_all('td')]
            if len(cols) < 15:
                continue
            try:
                results.append({
                    'date':      cols[0],
                    'race_name': cols[4],
                    'horses':    int(cols[6]) if cols[6].isdigit() else 10,
                    'odds':      float(cols[9]) if cols[9].replace('.','').isdigit() else 10.0,
                    'popularity':int(cols[10]) if cols[10].isdigit() else 10,
                    'rank':      int(cols[11]) if cols[11].isdigit() else 10,
                    'distance':  int(re.sub(r'\D','', cols[14])) if re.search(r'\d', cols[14]) else 2000,
                    'surface':   '芝' if cols[14].startswith('芝') else 'ダート',
                    'condition': cols[16] if len(cols) > 16 else '良',
                    'grade':     'G1' if 'GI)' in cols[4] and 'GII' not in cols[4] else
                                 'G2' if 'GII)' in cols[4] else
                                 'G3' if 'GIII)' in cols[4] else 'OP',
                })
            except Exception:
                continue
        return results
    except Exception as e:
        print(f'    [警告] {horse_name} の成績取得失敗: {e}')
        return []

# ----------------------------------------------------------------
# スコア計算
# ----------------------------------------------------------------
def calc_score(results, target_distance, target_surface):
    """
    0〜100点のスコアと詳細コメントを返す
    """
    if not results:
        return 40.0, {}, "過去成績データなし（スコア基準値）"

    detail = {}
    score  = 0.0

    # ── 1. 直近5走平均着順 (30pt) ──────────────────
    recent5 = [r for r in results[:5] if r['rank'] <= r['horses']]
    if recent5:
        avg_rank = sum(r['rank'] for r in recent5) / len(recent5)
        # 1着→30pt、5着→18pt、10着以下→5pt 線形補間
        pt = max(5.0, 30.0 - (avg_rank - 1) * 2.5)
        score += pt
        detail['直近5走平均'] = f"{avg_rank:.1f}着 → {pt:.0f}pt"
    else:
        score += 15.0
        detail['直近5走平均'] = "データ不足 → 15pt"

    # ── 2. 重賞好走実績 (20pt) ──────────────────────
    graded_top3 = [r for r in results if r['grade'] in ('G1','G2','G3') and r['rank'] <= 3]
    g1_win   = sum(1 for r in results if r['grade']=='G1' and r['rank']==1)
    g1_place = sum(1 for r in results if r['grade']=='G1' and r['rank']<=3)
    g2_place = sum(1 for r in results if r['grade']=='G2' and r['rank']<=3)
    grade_pt = min(20.0, g1_win * 10 + g1_place * 6 + g2_place * 3)
    score += grade_pt
    detail['重賞実績'] = f"G1勝{g1_win}回 G1連対{g1_place}回 G2連対{g2_place}回 → {grade_pt:.0f}pt"

    # ── 3. 同距離±200m 勝率 (20pt) ─────────────────
    dist_races = [r for r in results if abs(r['distance'] - target_distance) <= 200]
    if dist_races:
        dist_wins  = sum(1 for r in dist_races if r['rank'] == 1)
        dist_top3  = sum(1 for r in dist_races if r['rank'] <= 3)
        win_rate   = dist_wins / len(dist_races)
        top3_rate  = dist_top3 / len(dist_races)
        dist_pt    = min(20.0, win_rate * 30 + top3_rate * 10)
        score += dist_pt
        detail['距離適性'] = f"{target_distance}m±200 {len(dist_races)}走 {dist_wins}勝 → {dist_pt:.0f}pt"
    else:
        score += 8.0
        detail['距離適性'] = f"同距離実績なし → 8pt"

    # ── 4. 芝/ダート適性 (15pt) ─────────────────────
    surf_races = [r for r in results if r['surface'] == target_surface]
    if surf_races:
        surf_wins = sum(1 for r in surf_races if r['rank'] == 1)
        surf_rate = surf_wins / len(surf_races)
        surf_pt   = min(15.0, surf_rate * 20 + (len(surf_races) >= 5) * 3)
        score += surf_pt
        detail['馬場適性'] = f"{target_surface} {len(surf_races)}走 {surf_wins}勝 → {surf_pt:.0f}pt"
    else:
        score += 5.0
        detail['馬場適性'] = f"{target_surface}実績なし → 5pt"

    # ── 5. 馬場状態適性 (15pt) ──────────────────────
    # 本日大阪杯は「稍重」→ 稍重・重・不良での成績を加点
    all_wet  = [r for r in results if r['condition'] in ('稍重','重','不良')]
    wet_wins = sum(1 for r in all_wet if r['rank'] == 1)
    wet_top3 = sum(1 for r in all_wet if r['rank'] <= 3)
    if all_wet:
        wet_rate = wet_top3 / len(all_wet)
        wet_pt   = min(15.0, wet_wins * 8 + wet_rate * 10)
    else:
        wet_pt = 5.0
    score += wet_pt
    detail['稍重適性'] = f"稍重以上 {len(all_wet)}走 {wet_wins}勝 → {wet_pt:.0f}pt"

    # 100点満点に正規化（最大は 30+20+20+15+15=100）
    score = round(min(100.0, max(0.0, score)), 1)
    return score, detail, build_comment(results, target_distance, target_surface, detail)

def build_comment(results, dist, surf, detail):
    parts = []
    recent5 = results[:5]
    if recent5:
        ranks = [r['rank'] for r in recent5 if r['rank'] <= r['horses']]
        if ranks:
            avg = sum(ranks) / len(ranks)
            if avg <= 2.5:
                parts.append("直近5走の状態が非常に良い")
            elif avg <= 4.0:
                parts.append("直近5走は安定した走り")
            else:
                parts.append("直近成績は苦戦傾向")

    dist_wins = len([r for r in results if abs(r['distance']-dist)<=200 and r['rank']==1])
    if dist_wins >= 2:
        parts.append(f"この距離で{dist_wins}勝と得意")
    elif dist_wins == 1:
        parts.append("この距離での勝利実績あり")

    wet = [r for r in results if r['condition'] in ('稍重','重','不良')]
    wet_wins = len([r for r in wet if r['rank']==1])
    if wet_wins >= 1:
        parts.append(f"稍重以上で{wet_wins}勝と馬場適性高い")
    elif wet and all(r['rank'] >= 5 for r in wet):
        parts.append("稍重以上の成績は良くない")

    g1_wins = len([r for r in results if r['grade']=='G1' and r['rank']==1])
    if g1_wins >= 1:
        parts.append(f"G1・{g1_wins}勝の実績馬")

    return "。".join(parts) if parts else "特徴的なポイントなし"

# ----------------------------------------------------------------
# メイン
# ----------------------------------------------------------------
def main():
    race_name = sys.argv[1] if len(sys.argv) > 1 else '大阪杯'
    dry_run   = '--dry-run' in sys.argv

    print(f"{'='*60}")
    print(f"  統計ベース予想（APIなし）: {race_name}")
    print(f"  本日馬場: 稍重（雨）")
    print(f"{'='*60}\n")

    conn = get_conn()
    ensure_stats_table(conn)

    entries = get_entries(conn, race_name)
    if not entries:
        print(f"❌ {race_name} の出走馬データがDBにありません")
        print("  先に出走馬取得を実行してください")
        conn.close()
        return

    # 距離・馬場を取得
    target_distance = entries[0][4] or 2000
    target_surface  = entries[0][5] or '芝'
    race_date       = entries[0][6]
    print(f"レース条件: {target_distance}m {target_surface} ({race_date})\n")
    print(f"出走馬: {len(entries)}頭\n")

    scored = []
    for horse_name, horse_id, horse_num, jockey, dist, surf, _ in entries:
        print(f"  {horse_num}番 {horse_name} ({jockey})")
        if not horse_id:
            print(f"    [スキップ] horse_id なし")
            scored.append({
                'horse_name': horse_name, 'horse_id': horse_id,
                'horse_num': horse_num, 'jockey': jockey,
                'score': 40.0, 'detail': {}, 'comment': '成績データなし'
            })
            continue
        results = fetch_horse_results(horse_id, horse_name)
        score, detail, comment = calc_score(results, target_distance or 2000, target_surface or '芝')
        print(f"    スコア: {score:.1f}点 | {comment}")
        scored.append({
            'horse_name': horse_name, 'horse_id': horse_id,
            'horse_num': horse_num,  'jockey': jockey,
            'score': score, 'detail': detail, 'comment': comment,
            'results_count': len(results),
        })
        time.sleep(0.8)

    # 順位付け
    scored.sort(key=lambda x: x['score'], reverse=True)

    print(f"\n{'='*60}")
    print(f"  ★ {race_name} 予想結果 ★")
    print(f"{'='*60}")
    rank_mark = {1:'◎', 2:'○', 3:'▲', 4:'△', 5:'×'}
    for i, h in enumerate(scored, 1):
        mark = rank_mark.get(i, ' ')
        print(f"  {mark} {i}位: {h['horse_name']} ({h['score']:.1f}点)")
        print(f"       {h['comment']}")

    if not dry_run:
        # DB保存
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM stats_prediction WHERE race_name = %s", (race_name,))
            for i, h in enumerate(scored, 1):
                cur.execute("""
                    INSERT INTO stats_prediction
                        (race_name, horse_name, horse_id, rank_position, score, score_detail, comment)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                """, (
                    race_name, h['horse_name'], h['horse_id'], i,
                    h['score'], json.dumps(h['detail'], ensure_ascii=False), h['comment']
                ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
        print(f"\n✅ {race_name} の統計予想をDBに保存しました")
        print(f"   → /stats-predict?raceName={race_name} で確認")

    conn.close()
    print(f"\n{'='*60}")
    print(f"  RESULT:{json.dumps({'success':True,'race':race_name,'top3':[s['horse_name'] for s in scored[:3]]}, ensure_ascii=False)}")

if __name__ == '__main__':
    main()
