"""
stats_predictor.py  ― APIなし・統計ベース予想

netkeiba から各馬の過去成績をスクレイピングし、以下の指標でスコアリング。
Claude Vision API は一切使用しない。

スコア要素:
  1. 直近5走平均着順 (25pt)  ← 低いほど良い
  2. G1/G2 好走実績 (15pt)
  3. 同距離±200m 勝率 (15pt)
  4. 芝/ダート 適性 (10pt)
  5. 重馬場適性 (本日の馬場状態に応じて加点) (10pt)
  6. 調教評価 (15pt)  ← netkeiba 追い切り評価ランク(S/A〜E)
  7. 血統適性 (10pt)  ← 父・母父の距離/馬場適性と今回条件の合致

使い方:
  python stats_predictor.py 大阪杯
  python stats_predictor.py 大阪杯 --dry-run  # DB保存なし
"""

import sys, os, re, time, json
import psycopg2
from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv
from constants import HEADERS, fetch_with_retry, polite_sleep

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

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
            horse_number INTEGER,
            rank_position INTEGER,
            score        FLOAT,
            face_score   FLOAT,
            score_detail TEXT,
            comment      TEXT,
            face_comment TEXT,
            image_path   VARCHAR(500),
            jockey_name  VARCHAR(100),
            face_analyzed_at TIMESTAMP,
            created_at   TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()

# ----------------------------------------------------------------
# 調教評価（netkeiba 追い切りページ・評価ランクは無料で閲覧可）
# ----------------------------------------------------------------
TRAINING_PT = {'S': 15.0, 'A': 13.0, 'B': 10.0, 'C': 6.0, 'D': 3.0, 'E': 1.0}
TRAINING_DEFAULT = 7.0  # 評価なし（地方・海外・データ未掲載）は中立

def fetch_oikiri_ranks(race_id):
    """追い切りページから {馬名: 評価ランク(S/A〜E)} を取得。失敗時は空dict。"""
    ranks = {}
    if not race_id:
        return ranks
    try:
        url = f"https://race.netkeiba.com/race/oikiri.html?race_id={race_id}"
        resp = fetch_with_retry(url, timeout=15, min_sleep=1.0, max_sleep=2.0)
        resp.encoding = 'EUC-JP'
        soup = BeautifulSoup(resp.text, 'lxml')
        for row in soup.find_all('tr', class_=re.compile(r'OikiriDataHead')):
            link = row.find('a', href=re.compile(r'/horse/'))
            if not link:
                continue
            name = link.get_text(strip=True)
            rank_td = row.find('td', class_=re.compile(r'^Rank_'))
            if rank_td:
                rank = rank_td.get_text(strip=True).upper()
                if rank in TRAINING_PT:
                    ranks[name] = rank
    except Exception as e:
        print(f"  [警告] 調教評価の取得失敗: {e}")
    return ranks

# ----------------------------------------------------------------
# 血統適性（父・母父の代表的な適性分類）
# ----------------------------------------------------------------
# カテゴリ: sprint(〜1400) / mile(1600-1800) / middle(2000-2200) / long(2400〜) / dirt
SIRE_APTITUDE = {
    # 芝中長距離系
    'ディープインパクト': {'mile', 'middle', 'long'},
    'ハーツクライ':       {'middle', 'long'},
    'キズナ':             {'mile', 'middle'},
    'コントレイル':       {'mile', 'middle'},
    'オルフェーヴル':     {'middle', 'long'},
    'ゴールドシップ':     {'long'},
    'キタサンブラック':   {'middle', 'long'},
    'ドゥラメンテ':       {'mile', 'middle', 'long'},
    'エピファネイア':     {'middle', 'long'},
    'ルーラーシップ':     {'middle', 'long'},
    'ハービンジャー':     {'middle', 'long'},
    'スワーヴリチャード': {'mile', 'middle'},
    'サートゥルナーリア': {'mile', 'middle'},
    'レイデオロ':         {'middle'},
    'ステイゴールド':     {'middle', 'long'},
    'ディープブリランテ': {'mile', 'middle'},
    'シルバーステート':   {'mile', 'middle'},
    'リアルスティール':   {'mile', 'middle'},
    'サトノダイヤモンド': {'middle', 'long'},
    'イスラボニータ':     {'mile'},
    'ジャスタウェイ':     {'mile', 'middle'},
    'スクリーンヒーロー': {'middle'},
    'ブラックタイド':     {'middle', 'long'},
    'ノヴェリスト':       {'middle', 'long'},
    'マカヒキ':           {'middle'},
    'ワールドエース':     {'mile', 'middle'},
    'フィエールマン':     {'long'},
    'アリストテレス':     {'middle', 'long'},
    # 芝短距離・マイル系
    'ロードカナロア':     {'sprint', 'mile'},
    'ダイワメジャー':     {'sprint', 'mile'},
    'キンシャサノキセキ': {'sprint'},
    'ビッグアーサー':     {'sprint'},
    'モーリス':           {'mile', 'middle'},
    'ミッキーアイル':     {'sprint', 'mile'},
    'グランアレグリア':   {'sprint', 'mile'},
    'アドマイヤマーズ':   {'mile'},
    'インディチャンプ':   {'sprint', 'mile'},
    'タワーオブロンドン': {'sprint'},
    # ダート系
    'ヘニーヒューズ':     {'dirt'},
    'シニスターミニスター': {'dirt'},
    'パイロ':             {'dirt'},
    'ドレフォン':         {'dirt', 'sprint'},
    'マインドユアビスケッツ': {'dirt', 'sprint'},
    'ホッコータルマエ':   {'dirt'},
    'コパノリッキー':     {'dirt'},
    'ゴールドアリュール': {'dirt'},
    'キングカメハメハ':   {'mile', 'middle', 'dirt'},
    'ロージズインメイ':   {'dirt'},
    'サウスヴィグラス':   {'dirt', 'sprint'},
    # 海外系
    'Kingman':            {'mile'},
    'Frankel':            {'mile', 'middle'},
    'Siyouni':            {'sprint', 'mile'},
    'Into Mischief':      {'dirt', 'sprint'},
    'American Pharoah':   {'dirt', 'middle'},
}

def _clean_horse_label(text):
    """血統表セルから馬名のみ抽出（生年・毛色・リンク注記を除去）"""
    name = re.split(r'\d{4}', text)[0]
    return name.replace('[ 血統 ]', '').replace('[ 産駒 ]', '').strip()

def fetch_blood(horse_id):
    """5代血統表ページから (父, 母父) を取得。失敗時は (None, None)。"""
    if not horse_id:
        return None, None
    try:
        url = f"https://db.netkeiba.com/horse/ped/{horse_id}/"
        resp = fetch_with_retry(url, timeout=15, min_sleep=1.0, max_sleep=2.0)
        text = resp.content.decode('EUC-JP', errors='replace')
        soup = BeautifulSoup(text, 'lxml')
        table = soup.find('table', class_=re.compile(r'blood_table'))
        if not table:
            return None, None
        tds = table.find_all('td')
        if len(tds) < 33:
            return None, None
        sire    = _clean_horse_label(tds[0].get_text(' ', strip=True))
        bm_sire = _clean_horse_label(tds[32].get_text(' ', strip=True))
        return sire or None, bm_sire or None
    except Exception:
        return None, None

def calc_blood_pt(sire, bm_sire, target_category):
    """血統適性 0〜10pt。父6pt + 母父4pt（適性合致時）。不明は中立扱い。"""
    detail_parts = []
    pt = 0.0
    for name, weight, label in ((sire, 6.0, '父'), (bm_sire, 4.0, '母父')):
        if not name:
            pt += weight * 0.5  # データなしは中立（半分）
            continue
        apt = SIRE_APTITUDE.get(name)
        if apt is None:
            pt += weight * 0.5  # テーブル未登録も中立
            detail_parts.append(f"{label}{name}(未分類)")
        elif target_category in apt:
            pt += weight
            detail_parts.append(f"{label}{name}◎")
        else:
            detail_parts.append(f"{label}{name}×")
    return round(pt, 1), '、'.join(detail_parts) if detail_parts else 'データなし'

def classify_target(distance, surface):
    if surface == 'ダート':
        return 'dirt'
    d = distance or 2000
    if d <= 1400: return 'sprint'
    if d <= 1800: return 'mile'
    if d <= 2200: return 'middle'
    return 'long'

# ----------------------------------------------------------------
# 出走馬を取得
# ----------------------------------------------------------------
def get_entries(conn, race_name):
    cur = conn.cursor()
    # 同名レースが複数開催分（別年・別会場）残っている場合に混ざらないよう、
    # 最新の race_date の race_id に限定する
    cur.execute("""
        SELECT horse_name, horse_id, horse_number, jockey_name,
               distance, surface, race_date, race_id
        FROM race_entry
        WHERE race_name = %s
          AND race_id = (
              SELECT race_id FROM race_entry
              WHERE race_name = %s
              ORDER BY race_date DESC, race_id DESC LIMIT 1
          )
        ORDER BY horse_number
    """, (race_name, race_name))
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
        r = fetch_with_retry(url, timeout=15, min_sleep=1.5, max_sleep=3.0)
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
                    'horses':    int(cols[6]) if cols[6].strip().isdigit() else 10,
                    'odds':      (lambda v: float(v) if v.replace('.','',1).isdigit() else 10.0)(cols[9].strip()),
                    'popularity':int(cols[10]) if cols[10].strip().isdigit() else 10,
                    'rank':      int(cols[11]) if cols[11].strip().isdigit() else 10,
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
def calc_score(results, target_distance, target_surface,
               training_rank=None, blood=None):
    """
    0〜100点のスコアと詳細コメントを返す
    training_rank: 追い切り評価 'S'/'A'〜'E' or None
    blood: (父, 母父) or None
    """
    detail = {}
    score  = 0.0

    if not results:
        # 過去成績なしでも調教・血統は評価できる
        score = 25.0  # 成績系5ファクター分の基準値
        detail['過去成績'] = "データなし → 基準25pt"
    else:
        # ── 1. 直近5走平均着順 (25pt) ──────────────────
        recent5 = [r for r in results[:5] if r['rank'] <= r['horses']]
        if recent5:
            avg_rank = sum(r['rank'] for r in recent5) / len(recent5)
            # 1着→25pt、5着→約17pt、10着以下→4pt 線形補間
            pt = max(4.0, 25.0 - (avg_rank - 1) * 2.1)
            score += pt
            detail['直近5走平均'] = f"{avg_rank:.1f}着 → {pt:.0f}pt"
        else:
            score += 12.0
            detail['直近5走平均'] = "データ不足 → 12pt"

        # ── 2. 重賞好走実績 (15pt) ──────────────────────
        g1_win   = sum(1 for r in results if r['grade']=='G1' and r['rank']==1)
        g1_place = sum(1 for r in results if r['grade']=='G1' and r['rank']<=3)
        g2_place = sum(1 for r in results if r['grade']=='G2' and r['rank']<=3)
        grade_pt = min(15.0, g1_win * 8 + g1_place * 5 + g2_place * 2.5)
        score += grade_pt
        detail['重賞実績'] = f"G1勝{g1_win}回 G1連対{g1_place}回 G2連対{g2_place}回 → {grade_pt:.0f}pt"

        # ── 3. 同距離±200m 勝率 (15pt) ─────────────────
        dist_races = [r for r in results if abs(r['distance'] - target_distance) <= 200]
        if dist_races:
            dist_wins  = sum(1 for r in dist_races if r['rank'] == 1)
            dist_top3  = sum(1 for r in dist_races if r['rank'] <= 3)
            win_rate   = dist_wins / len(dist_races)
            top3_rate  = dist_top3 / len(dist_races)
            dist_pt    = min(15.0, win_rate * 22 + top3_rate * 8)
            score += dist_pt
            detail['距離適性'] = f"{target_distance}m±200 {len(dist_races)}走 {dist_wins}勝 → {dist_pt:.0f}pt"
        else:
            score += 6.0
            detail['距離適性'] = f"同距離実績なし → 6pt"

        # ── 4. 芝/ダート適性 (10pt) ─────────────────────
        surf_races = [r for r in results if r['surface'] == target_surface]
        if surf_races:
            surf_wins = sum(1 for r in surf_races if r['rank'] == 1)
            surf_rate = surf_wins / len(surf_races)
            surf_pt   = min(10.0, surf_rate * 13 + (len(surf_races) >= 5) * 2)
            score += surf_pt
            detail['馬場適性'] = f"{target_surface} {len(surf_races)}走 {surf_wins}勝 → {surf_pt:.0f}pt"
        else:
            score += 3.5
            detail['馬場適性'] = f"{target_surface}実績なし → 3.5pt"

        # ── 5. 馬場状態適性 (10pt) ──────────────────────
        all_wet  = [r for r in results if r['condition'] in ('稍重','重','不良')]
        wet_wins = sum(1 for r in all_wet if r['rank'] == 1)
        wet_top3 = sum(1 for r in all_wet if r['rank'] <= 3)
        if all_wet:
            wet_rate = wet_top3 / len(all_wet)
            wet_pt   = min(10.0, wet_wins * 5 + wet_rate * 7)
        else:
            wet_pt = 3.5
        score += wet_pt
        detail['稍重適性'] = f"稍重以上 {len(all_wet)}走 {wet_wins}勝 → {wet_pt:.0f}pt"

    # ── 6. 調教評価 (15pt) ──────────────────────────
    if training_rank in TRAINING_PT:
        train_pt = TRAINING_PT[training_rank]
        detail['調教評価'] = f"追い切り{training_rank}評価 → {train_pt:.0f}pt"
    else:
        train_pt = TRAINING_DEFAULT
        detail['調教評価'] = f"評価なし → {train_pt:.0f}pt"
    score += train_pt

    # ── 7. 血統適性 (10pt) ──────────────────────────
    sire, bm_sire = blood if blood else (None, None)
    target_cat = classify_target(target_distance, target_surface)
    blood_pt, blood_desc = calc_blood_pt(sire, bm_sire, target_cat)
    score += blood_pt
    detail['血統適性'] = f"{blood_desc} → {blood_pt:.1f}pt"

    # 100点満点に正規化（最大は 25+15+15+10+10+15+10=100）
    score = round(min(100.0, max(0.0, score)), 1)
    if not results:
        return score, detail, "過去成績データなし（調教・血統のみで評価）"
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
    update_mode = '--update' in sys.argv  # 顔面データを保持してスコアのみ再評価

    # race_id（数字のみ）が渡された場合はレース名に解決する（VNCの日本語化け対策）
    if race_name.isdigit():
        conn0 = get_conn()
        cur0 = conn0.cursor()
        cur0.execute("SELECT race_name FROM race_entry WHERE race_id = %s LIMIT 1", (race_name,))
        row0 = cur0.fetchone()
        cur0.close(); conn0.close()
        if not row0:
            print(f"❌ race_id={race_name} のデータが race_entry にありません")
            return
        race_name = row0[0]
        print(f"race_id から解決: {race_name}")

    print(f"{'='*60}")
    print(f"  統計ベース予想（APIなし）: {race_name}")
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
    race_id         = entries[0][7]
    print(f"レース条件: {target_distance}m {target_surface} ({race_date})\n")
    print(f"出走馬: {len(entries)}頭\n")

    # 調教評価をレース単位で一括取得（1リクエスト）
    oikiri_ranks = fetch_oikiri_ranks(race_id)
    if oikiri_ranks:
        print(f"調教評価: {len(oikiri_ranks)}頭分取得\n")
    else:
        print("調教評価: 取得なし（中立扱い）\n")

    scored = []
    for horse_name, horse_id, horse_num, jockey, dist, surf, _, _rid in entries:
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
        blood   = fetch_blood(horse_id)
        score, detail, comment = calc_score(results, target_distance or 2000, target_surface or '芝',
                                            training_rank=oikiri_ranks.get(horse_name),
                                            blood=blood)
        print(f"    スコア: {score:.1f}点 | {comment}")
        scored.append({
            'horse_name': horse_name, 'horse_id': horse_id,
            'horse_num': horse_num,  'jockey': jockey,
            'score': score, 'detail': detail, 'comment': comment,
            'results_count': len(results),
        })
        polite_sleep(1.5, 3.0)

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
            if update_mode:
                # 更新モード: 顔面分析データ（face_*）を保持したままスコアのみ更新。
                # 直前再評価（最新の調教評価の反映）用。
                updated = inserted = 0
                for i, h in enumerate(scored, 1):
                    cur.execute("""
                        UPDATE stats_prediction
                        SET rank_position = %s, score = %s, score_detail = %s, comment = %s
                        WHERE race_name = %s AND horse_name = %s
                    """, (i, h['score'], json.dumps(h['detail'], ensure_ascii=False),
                          h['comment'], race_name, h['horse_name']))
                    if cur.rowcount > 0:
                        updated += cur.rowcount
                    else:
                        cur.execute("""
                            INSERT INTO stats_prediction
                                (race_name, horse_name, horse_id, rank_position, score, score_detail, comment)
                            VALUES (%s,%s,%s,%s,%s,%s,%s)
                        """, (race_name, h['horse_name'], h['horse_id'], i,
                              h['score'], json.dumps(h['detail'], ensure_ascii=False), h['comment']))
                        inserted += 1
                conn.commit()
                print(f"\n✅ {race_name} のスコアを再評価しました（更新{updated}頭・追加{inserted}頭、顔面データ保持）")
            else:
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
                print(f"\n✅ {race_name} の統計予想をDBに保存しました")
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
        print(f"   → /stats-predict?raceName={race_name} で確認")

    conn.close()
    print(f"\n{'='*60}")
    print(f"  RESULT:{json.dumps({'success':True,'race':race_name,'top3':[s['horse_name'] for s in scored[:3]]}, ensure_ascii=False)}")

if __name__ == '__main__':
    main()
