"""
weekly_pipeline.py — 週次自動予想パイプライン

処理順序:
  1. 今日から14日以内の重賞・OP・リステッドを検索
  2. 出馬表 + 写真をDBに保存（entry_fetcher）
  3. 統計予想を実行（stats_predictor）
  4. 顔面分析を実行（face_analyzer_local）
  5. stats_predictionのimage_path/jockey/horse_numberをrace_entryからJOINで更新

使い方:
  python weekly_pipeline.py            # 今日から14日以内を全処理
  python weekly_pipeline.py --dry-run  # 対象レース一覧のみ表示
"""

import sys, os, time, json, subprocess
from datetime import datetime, timedelta
import requests, re, psycopg2
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
PYTHON  = sys.executable
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def fetch_upcoming_grade_races(days=14):
    """今日から days 日以内の重賞・OP・リステッドを返す"""
    today = datetime.now()
    results = []
    for delta in range(0, days + 1):
        d = today + timedelta(days=delta)
        url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={d.strftime('%Y%m%d')}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.encoding = 'utf-8'
            soup = BeautifulSoup(resp.text, 'lxml')
            for li in soup.find_all('li', class_='RaceList_DataItem'):
                if not li.find('span', class_=re.compile(r'Icon_GradeType\d')):
                    continue
                a = li.find('a', href=re.compile(r'shutuba'))
                if not a:
                    continue
                title_span = li.find('span', class_='ItemTitle')
                race_name = title_span.text.strip() if title_span else a.text.strip().split('\n')[0]
                href = a.get('href', '')
                m = re.search(r'race_id=(\d+)', href)
                if m:
                    results.append({
                        'race_id': m.group(1),
                        'race_name': race_name,
                        'race_date': d.date(),
                    })
            time.sleep(0.3)
        except Exception as e:
            log(f"  [警告] {d.strftime('%Y%m%d')} の取得失敗: {e}")
    return results

NOISE_PATTERNS = [
    'NotOpenSSLWarning', 'urllib3', 'warnings.warn',
    'site-packages', 'LibreSSL',
]

def run_script(script_name, args, desc):
    """サブスクリプトを実行し、ログを逐次出力"""
    cmd = [PYTHON, os.path.join(SCRIPT_DIR, script_name)] + args
    log(f"  → {desc} 開始")
    env = os.environ.copy()
    env['PYTHONWARNINGS'] = 'ignore'
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, env=env,
        cwd=os.path.dirname(SCRIPT_DIR)
    )
    output_lines = []
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        if any(p in line for p in NOISE_PATTERNS):
            continue
        print(f"      {line}", flush=True)
        output_lines.append(line)
    proc.wait()
    success = proc.returncode == 0
    log(f"  → {desc} {'完了 ✅' if success else '失敗 ❌'}")
    return success, output_lines

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST','localhost'), port=os.getenv('DB_PORT','5432'),
        dbname=os.getenv('DB_NAME','faceapp'), user=os.getenv('DB_USER','postgres'),
        password=os.getenv('DB_PASSWORD','postgrestest')
    )

def already_has_entries(race_id):
    """race_entry に既にデータがあるか"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM race_entry WHERE race_id = %s", (race_id,))
            return cur.fetchone()[0] > 0
        finally:
            cur.close()
    finally:
        conn.close()

def already_has_stats(race_name):
    """stats_prediction に既にデータがあるか"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM stats_prediction WHERE race_name = %s", (race_name,))
            return cur.fetchone()[0] > 0
        finally:
            cur.close()
    finally:
        conn.close()

def face_analysis_done(race_name):
    """全馬の顔面分析が完了しているか"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT COUNT(*), COUNT(face_comment)
                FROM stats_prediction WHERE race_name = %s
            """, (race_name,))
            total, done = cur.fetchone()
            return total > 0 and total == done
        finally:
            cur.close()
    finally:
        conn.close()

def update_image_paths(race_name):
    """stats_predictionのimage_path等をrace_entryからJOINして更新"""
    conn = get_conn()
    try:
        cur = conn.cursor()
        try:
            cur.execute("""
                UPDATE stats_prediction sp
                SET image_path    = '/uploads/candidates/' || re.horse_id || '.jpg',
                    jockey_name   = re.jockey_name,
                    horse_number  = re.horse_number
                FROM race_entry re
                WHERE sp.race_name = re.race_name
                  AND sp.horse_name = re.horse_name
                  AND sp.race_name  = %s
            """, (race_name,))
            updated = cur.rowcount
            conn.commit()
            return updated
        finally:
            cur.close()
    finally:
        conn.close()

def main():
    dry_run = '--dry-run' in sys.argv

    log("=" * 60)
    log("  週次重賞予想パイプライン 開始")
    log("=" * 60)

    races = fetch_upcoming_grade_races(days=14)

    if not races:
        log("❌ 対象レースが見つかりませんでした")
        return

    log(f"\n対象レース: {len(races)}件")
    for r in races:
        log(f"  {r['race_date']} {r['race_name']} ({r['race_id']})")

    if dry_run:
        log("\n[dry-run] ここで終了します")
        return

    log("")
    results = []

    for i, race in enumerate(races, 1):
        race_name = race['race_name']
        race_id   = race['race_id']

        log(f"\n{'─'*50}")
        log(f"[{i}/{len(races)}] {race['race_date']} {race_name}")
        log(f"{'─'*50}")

        # 1. 出馬表・写真取得（既にDBに存在する場合はスキップ）
        if already_has_entries(race_id):
            log(f"  → 出馬表: スキップ（DB既存）")
            ok1 = True
        else:
            # race_id を直接渡すことで再スクレイピングをスキップ
            ok1, _ = run_script('entry_fetcher.py',
                                 ['--race-id', race_id, race_name, str(race['race_date'])],
                                 '出馬表・写真取得')
            if not ok1:
                log(f"  ⚠️ {race_name} の出馬表取得に失敗、スキップ")
                results.append({'race': race_name, 'status': 'entry_failed'})
                continue

        # 2. 統計予想（既に存在する場合はスキップ）
        if already_has_stats(race_name):
            log(f"  → 統計予想: スキップ（DB既存）")
            ok2 = True
        else:
            ok2, _ = run_script('stats_predictor.py', [race_name], '統計予想')
            if not ok2:
                log(f"  ⚠️ {race_name} の統計予想に失敗、スキップ")
                results.append({'race': race_name, 'status': 'stats_failed'})
                continue

        # 3. image_path 更新
        updated = update_image_paths(race_name)
        if updated > 0:
            log(f"  → image_path 更新: {updated}頭")

        # 4. 顔面分析（全馬完了済みならスキップ）
        if face_analysis_done(race_name):
            log(f"  → 顔面分析: スキップ（全馬完了済み）")
            ok3 = True
        else:
            ok3, _ = run_script('face_analyzer_local.py', [race_name], '顔面分析（llava）')

        results.append({
            'race': race_name,
            'status': 'done' if ok3 else 'face_failed',
        })

        time.sleep(1)

    log(f"\n{'='*60}")
    log("  週次パイプライン 完了")
    log(f"{'='*60}")
    done  = sum(1 for r in results if r['status'] == 'done')
    fails = sum(1 for r in results if r['status'] != 'done')
    log(f"  成功: {done}レース  失敗/スキップ: {fails}レース")
    for r in results:
        icon = '✅' if r['status'] == 'done' else '❌'
        log(f"  {icon} {r['race']}")

    print(f"\nRESULT:{json.dumps({'success': True, 'done': done, 'total': len(results)})}", flush=True)

if __name__ == '__main__':
    main()
