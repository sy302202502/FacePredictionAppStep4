"""
result_auto_fetcher.py
レース後に実際の結果をnetkeibaからスクレイピングして的中記録を自動生成

【処理フロー】
  1. 予想データはあるが結果未記録のレースを検索
  2. grade_race_resultからrace_idを特定
  3. netkeibaから実際の着順をスクレイピング
  4. prediction_accuracy / race_specific_accuracy に記録
  5. 的中率サマリを表示

使い方:
  python result_auto_fetcher.py           # 全未記録レースを自動処理
  python result_auto_fetcher.py --dry-run # 対象レースの確認のみ
  python result_auto_fetcher.py --report  # 最新精度サマリを表示
"""
import sys
import os
import re
import time
import requests
import psycopg2
from bs4 import BeautifulSoup
from datetime import date
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest')
    )

def ensure_tables(conn):
    """race_specific_accuracy テーブルがなければ作成"""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_specific_accuracy (
            id SERIAL PRIMARY KEY,
            race_name VARCHAR(200),
            horse_name VARCHAR(100),
            predicted_rank INTEGER,
            actual_rank INTEGER,
            hit BOOLEAN DEFAULT FALSE,
            top5_hit BOOLEAN DEFAULT FALSE,
            score FLOAT,
            data_source VARCHAR(20) DEFAULT 'image',
            recorded_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()

# ------------------------------------------------------------------
# ① 未記録レースの検索
# ------------------------------------------------------------------
def find_unrecorded_old(conn):
    """prediction_resultにあるが的中記録がない過去レース"""
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT
            pr.target_race_name,
            pr.target_race_date,
            gr.race_id
        FROM prediction_result pr
        LEFT JOIN grade_race_result gr
            ON gr.race_name ILIKE '%%' || pr.target_race_name || '%%'
           AND ABS(gr.race_date - pr.target_race_date) <= 7
        WHERE NOT EXISTS (
            SELECT 1 FROM prediction_accuracy pa
            WHERE pa.race_name = pr.target_race_name
        )
        AND pr.target_race_date < CURRENT_DATE
        ORDER BY pr.target_race_date DESC
        LIMIT 30
    """)
    rows = cur.fetchall()
    cur.close()
    return rows  # (race_name, race_date, race_id_or_None)

def find_unrecorded_new(conn):
    """race_specific_resultにあるが的中記録がない過去レース"""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS race_specific_accuracy (
            id SERIAL PRIMARY KEY,
            race_name VARCHAR(200),
            horse_name VARCHAR(100),
            predicted_rank INTEGER,
            actual_rank INTEGER,
            hit BOOLEAN DEFAULT FALSE,
            top5_hit BOOLEAN DEFAULT FALSE,
            score FLOAT,
            data_source VARCHAR(20),
            recorded_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    # grade_race_result に JOIN できなくても race_specific_result 単体で取得
    # created_at が2日以上前 = レース当日以降に記録されたと仮定
    # 日付の近い race_id のみ使用（±14日）して年違いを防ぐ
    cur.execute("""
        SELECT DISTINCT
            rsr.race_name,
            COALESCE(gr.race_date, (rsr.created_at::date + INTERVAL '1 day')::date) AS race_date,
            gr.race_id
        FROM race_specific_result rsr
        LEFT JOIN grade_race_result gr
            ON gr.race_name ILIKE '%%' || rsr.race_name || '%%'
            AND gr.race_date BETWEEN (rsr.created_at::date - INTERVAL '7 days')
                                 AND (rsr.created_at::date + INTERVAL '14 days')
        WHERE NOT EXISTS (
            SELECT 1 FROM race_specific_accuracy rsa
            WHERE rsa.race_name = rsr.race_name
        )
        AND rsr.created_at < NOW() - INTERVAL '1 day'
        ORDER BY race_date DESC NULLS LAST
        LIMIT 30
    """)
    rows = cur.fetchall()
    cur.close()
    return rows

# ------------------------------------------------------------------
# ② netkeibaから実際の着順を取得
# ------------------------------------------------------------------
def scrape_actual_results(race_id):
    """
    race_idを使ってnetkeibaから全着順を取得
    戻り値: {horse_name: finish_rank, ...}
    """
    if not race_id:
        return {}
    url = f"https://db.netkeiba.com/race/{race_id}/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = 'EUC-JP'
        soup = BeautifulSoup(resp.text, 'lxml')
    except Exception as e:
        print(f"    [スクレイピングエラー] {e}")
        return {}

    result_table = soup.find('table', class_='race_table_01')
    if not result_table:
        return {}

    results = {}
    for row in result_table.find_all('tr')[1:]:
        cols = row.find_all('td')
        if not cols:
            continue
        try:
            rank = int(cols[0].text.strip())
        except ValueError:
            continue
        horse_link = cols[3].find('a') if len(cols) > 3 else None
        if horse_link:
            results[horse_link.text.strip()] = rank
    return results

def search_race_id_by_name(conn, race_name, race_date=None):
    """race_nameからrace_idを検索（近い日付優先）。DBになければnetkeibaを直接検索。"""
    cur = conn.cursor()
    if race_date:
        cur.execute("""
            SELECT race_id FROM grade_race_result
            WHERE race_name ILIKE %s
            ORDER BY ABS(race_date - %s::date)
            LIMIT 1
        """, (f"%{race_name}%", str(race_date)))
    else:
        cur.execute("""
            SELECT race_id FROM grade_race_result
            WHERE race_name ILIKE %s
            ORDER BY race_date DESC
            LIMIT 1
        """, (f"%{race_name}%",))
    row = cur.fetchone()
    cur.close()
    if row:
        return row[0]

    # DBに見つからない場合はnetkeibaを直接検索
    return search_race_id_from_netkeiba(race_name, race_date)


def search_race_id_from_netkeiba(race_name, race_date=None):
    """netkeibaのレース検索でrace_idを取得（DBにない場合のフォールバック）"""
    from datetime import datetime, timedelta
    try:
        # 検索対象の年月を決定
        if race_date:
            if isinstance(race_date, str):
                dt = datetime.strptime(str(race_date)[:10], '%Y-%m-%d')
            elif hasattr(race_date, 'year'):
                dt = datetime(race_date.year, race_date.month, race_date.day)
            else:
                dt = datetime.today()
        else:
            dt = datetime.today()

        # 検索キーワードを生成（S→ステークス などの略称も正規化）
        kw_variants = [race_name]
        # 略称展開
        if race_name.endswith('S') or race_name.endswith('Ｓ'):
            base = race_name[:-1]
            kw_variants.append(base + 'ステークス')
            kw_variants.append(base)
        # 不要な記号除去
        kw_variants.append(re.sub(r'[Ｓ\s　]', '', race_name))

        # 当月と前後月を検索（最大3ヶ月）
        months_to_check = []
        for delta in [0, -1, 1]:
            m_dt = dt + timedelta(days=delta*30)
            months_to_check.append((m_dt.year, m_dt.month))

        for year, mon in months_to_check:
            url = (
                "https://db.netkeiba.com/?pid=race_search_detail"
                f"&start_year={year}&start_mon={mon}"
                f"&end_year={year}&end_mon={mon}"
                "&grade[]=1&grade[]=2&grade[]=3&grade[]=4&grade[]=5&grade[]=6"
                "&track[]=1&track[]=2&sort=date&list=500"
            )
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.encoding = 'EUC-JP'
            soup = BeautifulSoup(resp.text, 'lxml')

            for a in soup.select('a[href*="/race/"]'):
                link_text = a.text.strip()
                href = a.get('href', '')
                m = re.search(r'/race/(\d{12})/?', href)
                if not m:
                    continue
                # いずれかのキーワードで部分一致
                if any(kw and kw in link_text for kw in kw_variants):
                    race_id = m.group(1)
                    print(f"    [netkeiba検索] {link_text} → race_id={race_id}")
                    return race_id

            time.sleep(1)

        print(f"    [netkeiba検索] '{race_name}' が見つかりませんでした")
        return None
    except Exception as e:
        print(f"    [netkeiba検索エラー] {e}")
        return None

# ------------------------------------------------------------------
# ③ 的中記録を保存
# ------------------------------------------------------------------
def record_old_system(conn, race_name, actual_results):
    """prediction_result → prediction_accuracy に記録"""
    if not actual_results:
        return 0
    cur = conn.cursor()
    cur.execute("""
        SELECT id, horse_name, rank_position, final_score, race_category, target_race_date
        FROM prediction_result
        WHERE target_race_name = %s
        ORDER BY rank_position
    """, (race_name,))
    predictions = cur.fetchall()
    if not predictions:
        cur.close()
        return 0

    race_date     = predictions[0][5]
    race_category = predictions[0][4]

    top5_names = [p[1] for p in predictions[:5]]
    actual_winner = next((name for name, rank in actual_results.items() if rank == 1), None)
    top5_hit = actual_winner in top5_names if actual_winner else False
    hit_1st = (predictions[0][1] == actual_winner) if actual_winner and predictions else False

    count = 0
    for pred_id, horse_name, pred_rank, final_score, cat, r_date in predictions:
        actual_rank = actual_results.get(horse_name)
        cur.execute("SELECT id FROM prediction_accuracy WHERE prediction_id = %s", (pred_id,))
        if cur.fetchone():
            cur.execute("""
                UPDATE prediction_accuracy
                SET actual_rank=%s, hit=%s, top5_hit=%s, recorded_at=NOW()
                WHERE prediction_id=%s
            """, (actual_rank, hit_1st and pred_rank == 1, top5_hit, pred_id))
        else:
            cur.execute("""
                INSERT INTO prediction_accuracy
                    (prediction_id, race_name, race_date, race_category,
                     horse_name, predicted_rank, actual_rank, hit, top5_hit, final_score)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (pred_id, race_name, race_date, cat,
                  horse_name, pred_rank, actual_rank,
                  hit_1st and pred_rank == 1, top5_hit, final_score))
        count += 1
    conn.commit()
    cur.close()
    return count

def record_new_system(conn, race_name, actual_results):
    """race_specific_result → race_specific_accuracy に記録"""
    if not actual_results:
        return 0
    cur = conn.cursor()
    cur.execute("""
        SELECT horse_name, rank_position, score, data_source
        FROM race_specific_result
        WHERE race_name = %s
        ORDER BY rank_position
    """, (race_name,))
    predictions = cur.fetchall()
    if not predictions:
        cur.close()
        return 0

    top5_names   = [p[0] for p in predictions[:5]]
    actual_winner = next((name for name, rank in actual_results.items() if rank == 1), None)
    top5_hit     = actual_winner in top5_names if actual_winner else False
    hit_1st      = (predictions[0][0] == actual_winner) if actual_winner and predictions else False

    cur.execute("DELETE FROM race_specific_accuracy WHERE race_name = %s", (race_name,))
    for horse_name, pred_rank, score, data_src in predictions:
        actual_rank = actual_results.get(horse_name)
        cur.execute("""
            INSERT INTO race_specific_accuracy
                (race_name, horse_name, predicted_rank, actual_rank,
                 hit, top5_hit, score, data_source, recorded_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        """, (race_name, horse_name, pred_rank, actual_rank,
              hit_1st and pred_rank == 1, top5_hit, score, data_src))
    conn.commit()
    cur.close()
    return len(predictions)

# ------------------------------------------------------------------
# ④ 精度サマリ表示
# ------------------------------------------------------------------
def show_report(conn):
    cur = conn.cursor()
    print("\n" + "="*55)
    print("  予測精度レポート（自動記録分）")
    print("="*55)

    # 旧システム
    cur.execute("""
        SELECT COUNT(DISTINCT race_name),
               SUM(CASE WHEN hit=TRUE THEN 1 ELSE 0 END),
               SUM(CASE WHEN top5_hit=TRUE THEN 1 ELSE 0 END)
        FROM prediction_accuracy
        WHERE predicted_rank=1 AND top5_hit IS NOT NULL
    """)
    r = cur.fetchone()
    if r and r[0]:
        total, wh, t5h = r
        print(f"\n  【旧システム予想】")
        print(f"  記録済み: {total}レース  1位的中:{wh}回({wh/total*100:.1f}%)  TOP5:{t5h}回({t5h/total*100:.1f}%)")

    # 新システム
    cur.execute("""
        SELECT COUNT(DISTINCT race_name),
               SUM(CASE WHEN hit=TRUE THEN 1 ELSE 0 END),
               SUM(CASE WHEN top5_hit=TRUE THEN 1 ELSE 0 END)
        FROM race_specific_accuracy
        WHERE predicted_rank=1
    """)
    r2 = cur.fetchone()
    if r2 and r2[0]:
        total, wh, t5h = r2
        print(f"\n  【顔面傾向分析予想（新）】")
        print(f"  記録済み: {total}レース  1位的中:{wh}回({wh/total*100:.1f}%)  TOP5:{t5h}回({t5h/total*100:.1f}%)")

    print("="*55)
    cur.close()

# ------------------------------------------------------------------
# メイン
# ------------------------------------------------------------------
def main():
    dry_run = '--dry-run' in sys.argv
    report  = '--report'  in sys.argv

    conn = get_conn()
    ensure_tables(conn)

    if report:
        show_report(conn)
        conn.close()
        return

    print("=== 的中記録 自動取得 ===\n")

    # 旧システム
    old_races = find_unrecorded_old(conn)
    print(f"旧システム未記録: {len(old_races)}レース")

    for race_name, race_date, race_id in old_races:
        print(f"\n  [{race_name}] {race_date}")
        rid = race_id or search_race_id_by_name(conn, race_name, race_date)
        if not rid:
            print(f"    [スキップ] race_idが特定できません")
            continue
        if dry_run:
            print(f"    [dry-run] race_id={rid}")
            continue
        actual = scrape_actual_results(rid)
        if not actual:
            print(f"    [スキップ] 結果が取得できません (race_id={rid})")
            time.sleep(1)
            continue
        winner = next((n for n, r in actual.items() if r == 1), '不明')
        print(f"    実際の1着: {winner}  ({len(actual)}頭分取得)")
        n = record_old_system(conn, race_name, actual)
        print(f"    → {n}件記録完了")
        time.sleep(1.5)

    # 新システム
    new_races = find_unrecorded_new(conn)
    print(f"\n新システム未記録: {len(new_races)}レース")

    for race_name, race_date, race_id in new_races:
        print(f"\n  [{race_name}] {race_date}")
        rid = race_id or search_race_id_by_name(conn, race_name, race_date)
        if not rid:
            print(f"    [スキップ] race_idが特定できません")
            continue
        if dry_run:
            print(f"    [dry-run] race_id={rid}")
            continue
        actual = scrape_actual_results(rid)
        if not actual:
            print(f"    [スキップ] 結果取得失敗")
            time.sleep(1)
            continue
        winner = next((n for n, r in actual.items() if r == 1), '不明')
        print(f"    実際の1着: {winner}")
        n = record_new_system(conn, race_name, actual)
        print(f"    → {n}件記録完了")
        time.sleep(1.5)

    if not dry_run:
        show_report(conn)

    conn.close()
    print("\n=== 完了 ===")

if __name__ == '__main__':
    main()
