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
import re, psycopg2
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from constants import HEADERS, fetch_with_retry, polite_sleep

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)
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
            resp = fetch_with_retry(url, timeout=10, min_sleep=1.0, max_sleep=2.0)
            resp.encoding = 'utf-8'
            soup = BeautifulSoup(resp.text, 'lxml')
            for li in soup.find_all('li', class_='RaceList_DataItem'):
                grade_span = li.find('span', class_=re.compile(r'Icon_GradeType\d'))
                if not grade_span:
                    continue
                # グレード番号（1=G1, 2=G2, 3=G3, その他=OP/L等）
                gm = re.search(r'Icon_GradeType(\d+)', ' '.join(grade_span.get('class', [])))
                grade_no = int(gm.group(1)) if gm else 99
                # 当日はリンクが shutuba.html → result.html 等に変わるため race_id で拾う
                a = li.find('a', href=re.compile(r'race_id=\d+'))
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
                        'grade_no': grade_no,
                    })
        except Exception as e:
            log(f"  [警告] {d.strftime('%Y%m%d')} の取得失敗: {e}")
    # race_id で重複排除（リンク形式変更などで同一レースを二重に拾った場合の保険）
    seen = set()
    unique = []
    for r in results:
        if r['race_id'] in seen:
            continue
        seen.add(r['race_id'])
        unique.append(r)
    return unique

import requests as _requests
import fcntl as _fcntl
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '').strip()
LOCK_FILE = '/tmp/weekly_pipeline.lock'

# デッドマンズスイッチ（起動しなかったことの検知）。
# healthchecks.io のチェックURLを .env の HEALTHCHECK_URL に設定すると有効化。
# 期限（例:毎朝9時+猶予）までに /success ping が来なければ外部から通知が飛ぶ。
HEALTHCHECK_URL = os.getenv('HEALTHCHECK_URL', '').strip()

def healthcheck_ping(suffix=''):
    """healthchecks.io へ ping。suffix='/start'|'/fail'|''（成功）。URL未設定なら何もしない。"""
    if not HEALTHCHECK_URL:
        return
    try:
        _requests.get(HEALTHCHECK_URL.rstrip('/') + suffix, timeout=10)
    except Exception as e:
        print(f"[警告] healthcheck ping失敗({suffix}): {e}", file=sys.stderr, flush=True)

def send_discord(content):
    """Discord Webhook に通知を送信。URL未設定なら何もしない。
    送信失敗時は stderr にも明示出力し、cron 経由のメール/ログで検知できるようにする。"""
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        resp = _requests.post(DISCORD_WEBHOOK_URL,
                              json={"content": content[:1900]},
                              timeout=10)
        if resp.status_code >= 400:
            msg = f"[ERROR] Discord通知HTTPエラー: status={resp.status_code} body={resp.text[:200]}"
            print(msg, file=sys.stderr, flush=True)
            log(msg)
    except Exception as e:
        msg = f"[ERROR] Discord通知失敗: {e}"
        print(msg, file=sys.stderr, flush=True)
        log(msg)


def acquire_pipeline_lock():
    """同一パイプラインの並行実行を防ぐ排他ロックを取得。
    既に別プロセスが実行中の場合は終了する（cron の二重起動対策）。"""
    f = open(LOCK_FILE, 'w')
    try:
        _fcntl.flock(f, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        f.write(str(os.getpid()))
        f.flush()
        return f
    except OSError:
        print("[INFO] 別のパイプラインが実行中のため終了します", flush=True)
        sys.exit(0)

NOISE_PATTERNS = [
    'NotOpenSSLWarning', 'urllib3', 'warnings.warn',
    'site-packages', 'LibreSSL',
]

# サブスクリプト1本あたりの最大実行時間（秒）。
# これを超えたら強制終了して次へ進む（1ステップのハングで全体が止まるのを防ぐ）。
SCRIPT_TIMEOUT = int(os.getenv('PIPELINE_SCRIPT_TIMEOUT', '900'))  # 15分

def run_script(script_name, args, desc):
    """サブスクリプトを実行し、ログを逐次出力。
    SCRIPT_TIMEOUT を超えたら強制終了して失敗扱いで戻る（ハング対策）。"""
    import threading
    cmd = [PYTHON, os.path.join(SCRIPT_DIR, script_name)] + args
    log(f"  → {desc} 開始")
    env = os.environ.copy()
    env['PYTHONWARNINGS'] = 'ignore'
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, env=env,
        cwd=os.path.dirname(SCRIPT_DIR)
    )

    # タイムアウト監視: 期限超過でプロセスツリーを強制終了する
    timed_out = {'flag': False}
    def _killer():
        timed_out['flag'] = True
        try:
            proc.kill()
        except Exception:
            pass
    timer = threading.Timer(SCRIPT_TIMEOUT, _killer)
    timer.start()

    output_lines = []
    try:
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            if any(p in line for p in NOISE_PATTERNS):
                continue
            print(f"      {line}", flush=True)
            output_lines.append(line)
        proc.wait()
    finally:
        timer.cancel()

    if timed_out['flag']:
        log(f"  ⛔ {desc} が {SCRIPT_TIMEOUT}秒を超過したため強制終了しました（ハング検知）")
        return False, output_lines
    success = proc.returncode == 0
    log(f"  → {desc} {'完了 ✅' if success else '失敗 ❌'}")
    return success, output_lines

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST','localhost'), port=os.getenv('DB_PORT','5432'),
        dbname=os.getenv('DB_NAME','faceapp'), user=os.getenv('DB_USER','postgres'),
        password=os.getenv('DB_PASSWORD') or sys.exit('[エラー] DB_PASSWORD 環境変数が設定されていません'),
        connect_timeout=int(os.getenv('PGCONNECT_TIMEOUT', '15')),
        # 1クエリが60秒を超えたら中断（停滞したコネクションでの無限待ちを防ぐ）
        options='-c statement_timeout=60000'
    )

def already_has_entries(conn, race_id):
    """race_entry に既にデータがあるか"""
    cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM race_entry WHERE race_id = %s", (race_id,))
        return cur.fetchone()[0] > 0
    finally:
        cur.close()

def already_has_stats(conn, race_name):
    """stats_prediction に既にデータがあるか。
    重賞・OP は毎年同名で開催されるため、昨年以前の残存データを「予想済み」と
    誤判定しないよう直近45日以内に作成された行だけを有効とみなす。
    （古い行は stats_predictor の全再生成時に DELETE で一掃される）"""
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT COUNT(*) FROM stats_prediction
            WHERE race_name = %s
              AND created_at > NOW() - INTERVAL '45 days'
        """, (race_name,))
        return cur.fetchone()[0] > 0
    finally:
        cur.close()

def face_analysis_done(conn, race_name, race_id):
    """当該 race_id の出走全馬の顔面分析が完了しているか。
    「このレース(race_name)の予想行で顔面済み、かつ現出走表(race_id)に居る馬」を数える。
    - race_name のみだと同名別開催や取消馬の残存行を巻き込み誤って完了判定する。
    - horse_id 単独JOINだと、同一馬が別レースで分析済みの行を過大カウントし、
      このレースが未分析でも「完了」と誤判定する（別形の偽完了バグ）。
    → race_name（このレースの予想）で絞りつつ、horse_id が現出走表に含まれるかで
      取消馬を除外する。末尾の重賞検証クエリと同一基準にしてズレを無くす。"""
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM race_entry WHERE race_id = %s),
                (SELECT COUNT(*) FROM stats_prediction sp
                 WHERE sp.race_name = %s
                   AND sp.face_comment IS NOT NULL
                   AND sp.horse_id IN (SELECT horse_id FROM race_entry WHERE race_id = %s))
        """, (race_id, race_name, race_id))
        heads, done = cur.fetchone()
        return heads > 0 and done >= heads
    finally:
        cur.close()

def update_image_paths(conn, race_name, race_id):
    """stats_predictionのimage_path等をrace_entryからJOINして更新。
    race_entry.race_name は scraped_name で保存され得るため、突合は race_name に
    依存せず race_id + horse_id で行う（predict_by_race_id.py と同一基準）。"""
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE stats_prediction sp
            SET image_path    = '/uploads/candidates/' || re.horse_id || '.jpg',
                jockey_name   = re.jockey_name,
                horse_number  = re.horse_number
            FROM race_entry re
            -- horse_name は表記揺れ・文字化けが起きうるため horse_id で突合。
            -- 対象開催は race_id で直接固定（同名過去開催の混入も防ぐ）。
            WHERE sp.horse_id = re.horse_id
              AND sp.race_name = %s
              AND re.race_id   = %s
        """, (race_name, race_id))
        updated = cur.rowcount
        conn.commit()
        return updated
    finally:
        cur.close()

def main():
    # 並行実行を防ぐロック取得（cronの二重起動・前回完了前の再起動を防止）
    _lock = acquire_pipeline_lock()
    dry_run = '--dry-run' in sys.argv

    log("=" * 60)
    log("  週次重賞予想パイプライン 開始")
    log("=" * 60)

    if not dry_run:
        healthcheck_ping('/start')  # 起動を外部監視に通知（来なければ「起動失敗」と判定される）

    races = fetch_upcoming_grade_races(days=14)

    if not races:
        log("❌ 対象レースが見つかりませんでした")
        send_discord(
            "⚠️ **週次パイプライン: 対象レース0件**\n"
            "14日以内の重賞・OP・Lが1件も取得できませんでした。\n"
            "netkeibaのHTML変更の可能性があります。要確認。"
        )
        healthcheck_ping('/fail')  # 異常終了として外部監視にも通知
        sys.exit(1)                # cron/ラッパも失敗を検知できるよう非0終了

    # 優先度順にソート: G1 → G2 → G3 → その他（同優先度は開催日が近い順）
    # 万馬券チャレンジ対象や多頭数レースは「直前再評価」の選定で別途優遇する
    GRADE_PRIORITY = {1: 0, 2: 1, 3: 2}
    races.sort(key=lambda r: (GRADE_PRIORITY.get(r.get('grade_no', 99), 3), r['race_date']))

    GRADE_LABEL = {1: 'G1', 2: 'G2', 3: 'G3'}
    log(f"\n対象レース: {len(races)}件（G1→G2→G3→その他の優先度順）")
    for r in races:
        label = GRADE_LABEL.get(r.get('grade_no', 99), 'OP/L')
        log(f"  [{label}] {r['race_date']} {r['race_name']} ({r['race_id']})")

    if dry_run:
        log("\n[dry-run] ここで終了します")
        return

    log("")

    # ── 0. 出馬表の最新同期（出走取消馬を予想から自動削除）──
    log("─" * 50)
    log("[0] 出馬表の最新同期（直前変更を反映）")
    log("─" * 50)
    ok_sync, _ = run_script('entry_fetcher.py', ['--sync'], '出馬表 同期')
    if not ok_sync:
        log("  ⚠️ 同期失敗（取消馬の反映ができていない可能性）")
        send_discord(
            "⚠️ **出馬表同期失敗**\n"
            "取消馬の反映ができていない可能性があります。\n"
            "本日のレース予想は手動確認を推奨します。"
        )

    results = []
    conn = get_conn()

    # 直前再評価の上限（1回の実行で再評価するレース数。負荷とBAN回避のため）
    REEVAL_LIMIT = 6
    reeval_count = 0

    try:
      for i, race in enumerate(races, 1):
       # ── レース単位のエラー隔離 ──
       # 1レースで予期せぬ例外が出ても、ループ全体を止めず次のレースへ進む。
       # （1レースのDB一時エラー等で重賞検証・Discord通知がスキップされる事故を防ぐ）
       try:
        race_name = race['race_name']
        race_id   = race['race_id']
        grade_no  = race.get('grade_no', 99)

        log(f"\n{'─'*50}")
        log(f"[{i}/{len(races)}] {race['race_date']} {race_name}")
        log(f"{'─'*50}")

        # 1. 出馬表・写真取得（既にDBに存在する場合はスキップ）
        if already_has_entries(conn, race_id):
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

        # 2. 統計予想（既に存在する場合はスキップ。ただし直前レースは再評価）
        if already_has_stats(conn, race_name):
            # ── 直前再評価 ──
            # レース前日〜当日は最終追い切り・枠順が確定しているため、
            # 優先度の高いレースだけスコアを再評価する（顔面データは保持）。
            # 優先度: G1/G2/G3 は無条件、その他は多頭数（14頭以上 = 高配当狙い目）のみ。
            # ※ 万馬券チャレンジ対象レースは多頭数OPが中心のため後者でカバーされる。
            days_to_race = (race['race_date'] - datetime.now().date()).days
            is_imminent  = 0 <= days_to_race <= 1
            if is_imminent and reeval_count < REEVAL_LIMIT:
                if grade_no in (1, 2, 3):
                    needs_reeval = True
                else:
                    cur_n = conn.cursor()
                    cur_n.execute("SELECT COUNT(*) FROM race_entry WHERE race_id = %s", (race_id,))
                    needs_reeval = cur_n.fetchone()[0] >= 14
                    cur_n.close()
                if needs_reeval:
                    log(f"  → 統計予想: 直前再評価（最新の調教評価を反映）")
                    ok2, _ = run_script('stats_predictor.py', [race_name, '--update'],
                                        '統計予想（再評価）')
                    reeval_count += 1
                    if not ok2:
                        log(f"  ⚠️ 再評価失敗（既存スコアを維持）")
                    ok2 = True  # 失敗しても既存予想があるので続行
                else:
                    log(f"  → 統計予想: スキップ（DB既存）")
                    ok2 = True
            else:
                log(f"  → 統計予想: スキップ（DB既存）")
                ok2 = True
        else:
            ok2, _ = run_script('stats_predictor.py', [race_name], '統計予想')
            if not ok2:
                log(f"  ⚠️ {race_name} の統計予想に失敗、スキップ")
                results.append({'race': race_name, 'status': 'stats_failed'})
                continue

        # 3. image_path 更新
        updated = update_image_paths(conn, race_name, race_id)
        if updated > 0:
            log(f"  → image_path 更新: {updated}頭")

        # 4. 顔面分析（全馬完了済みならスキップ）
        is_graded = grade_no in (1, 2, 3)
        if face_analysis_done(conn, race_name, race_id):
            log(f"  → 顔面分析: スキップ（全馬完了済み）")
            ok3 = True
        else:
            ok3, _ = run_script('face_analyzer_local.py', [race_name], '顔面分析（llava）')
            # G1〜G3は最重要。失敗 or 未完了なら即時もう一度だけ再試行する。
            if is_graded and not face_analysis_done(conn, race_name, race_id):
                log(f"  ⚠️ [重賞] {race_name} の顔面分析が未完了 → 即時リトライ")
                polite_sleep(3.0, 5.0)
                ok3, _ = run_script('face_analyzer_local.py', [race_name], '顔面分析リトライ（重賞）')

        results.append({
            'race': race_name,
            'race_id': race_id,
            'grade_no': grade_no,
            'status': 'done' if ok3 else 'face_failed',
        })

        polite_sleep(2.0, 4.0)
       except Exception as e:
        # このレースの処理で予期せぬ例外。記録して次のレースへ続行する。
        log(f"  ⛔ {race.get('race_name','?')} の処理中に例外: {e}")
        results.append({
            'race': race.get('race_name', '?'),
            'race_id': race.get('race_id'),
            'grade_no': race.get('grade_no', 99),
            'status': 'exception',
        })
        # DB接続が壊れた可能性に備えて作り直す
        try:
            conn.close()
        except Exception:
            pass
        try:
            conn = get_conn()
        except Exception:
            pass
    finally:
        conn.close()

    # ── 重賞（G1〜G3）の完了を明示検証 ──
    # 一般サマリでは見落とすため、重賞だけはDBで実完了を確認し、
    # 未完了があれば専用の強い警告をDiscordへ送る（G1欠落の再発防止）。
    graded_problems = []
    vconn = get_conn()
    try:
        for r in results:
            if r.get('grade_no') not in (1, 2, 3):
                continue
            vcur = vconn.cursor()
            # face_analysis_done() と同一基準（このレースの予想 × 現出走表の馬）。
            # horse_name 依存を排し、かつ他レースで分析済みの同一馬を過大カウントしない。
            vcur.execute("""
                SELECT
                    (SELECT COUNT(*) FROM race_entry WHERE race_id = %s) AS heads,
                    (SELECT COUNT(*) FROM stats_prediction sp
                     WHERE sp.race_name = %s
                       AND sp.face_comment IS NOT NULL
                       AND sp.horse_id IN (SELECT horse_id FROM race_entry WHERE race_id = %s)) AS face_done
            """, (r['race_id'], r['race'], r['race_id']))
            heads, face_done = vcur.fetchone()
            vcur.close()
            label = {1: 'G1', 2: 'G2', 3: 'G3'}[r['grade_no']]
            if heads == 0 or face_done < heads:
                graded_problems.append(f"{label} {r['race']}: 出走{heads}頭 / 顔面分析{face_done}頭")
                log(f"  ⛔ [重賞未完了] {label} {r['race']} 出走{heads} 顔面{face_done}")
            else:
                log(f"  ✅ [重賞OK] {label} {r['race']} {face_done}/{heads}頭")
    finally:
        vconn.close()

    if graded_problems:
        send_discord(
            "🚨 **【重要】重賞レースの予想が未完了です** 🚨\n"
            + "\n".join(f"・{p}" for p in graded_problems)
            + "\n\n手動で `predict_by_race_id.py <race_id>` を実行してください。"
        )

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

    # Discord通知（成功/失敗サマリ）
    today_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    icon = '✅' if fails == 0 else '⚠️'
    lines = [f"{icon} **週次予想パイプライン完了** ({today_str})",
             f"成功: {done}件 / 失敗: {fails}件"]
    for r in results:
        mark = '✅' if r['status'] == 'done' else f"❌ {r['status']}"
        lines.append(f"{mark} {r['race']}")
    lines.append("\nhttp://160.251.251.73:8081/predict-v2")
    send_discord("\n".join(lines))

    # デッドマンズスイッチ: 重賞未完了があれば /fail（外部監視も赤にする）、無ければ成功ping。
    healthcheck_ping('/fail' if graded_problems else '')

    # cron/ラッパが失敗を検知できるよう、重賞未完了や失敗レースありなら非0終了。
    # （__main__ の except は Exception のみ捕捉するため SystemExit は誤って
    #   「異常終了」通知を出さずにそのまま終了コードへ反映される）
    if graded_problems or fails > 0:
        sys.exit(1)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        # 致命的失敗もDiscordに通知
        import traceback
        err = traceback.format_exc()
        send_discord(f"🚨 **パイプライン異常終了**\n```\n{err[:1500]}\n```")
        raise
