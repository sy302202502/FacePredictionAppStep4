"""
scheduler.py
定期自動実行スクリプト
  - 毎週月曜 6時: 先週の重賞結果スクレイピング＋顔分析＋的中記録自動取得
  - 毎週木曜 6時: 翌週末の出走馬を自動取得
  - 毎週金曜 8時: 当日・翌日レースの予想をLINEへ自動通知

使い方:
  python scheduler.py           # 今すぐ全タスクを実行
  python scheduler.py weekly    # デーモン起動（毎週定期実行）
  python scheduler.py scrape    # スクレイピングのみ
  python scheduler.py entries   # 出走馬取得のみ
  python scheduler.py analyze   # 未分析の顔分析のみ
  python scheduler.py record    # 的中記録を自動取得のみ
  python scheduler.py notify    # 直近レースをLINE通知のみ

cronに登録する場合:
  # 毎週月曜 6時: 結果収集＋顔分析＋的中記録
  0 6 * * 1 cd ~/git/FacePredictionAppStep4/python && python scheduler.py scrape && python scheduler.py analyze && python scheduler.py record
  # 毎週木曜 6時: 出走馬取得
  0 6 * * 4 cd ~/git/FacePredictionAppStep4/python && python scheduler.py entries
  # 毎週金曜 8時: LINE通知
  0 8 * * 5 cd ~/git/FacePredictionAppStep4/python && python scheduler.py notify
"""
import sys
import os
import time
import subprocess
import psycopg2
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR  = os.path.join(SCRIPT_DIR, '../logs')
LOG_FILE = os.path.join(LOG_DIR, 'scheduler.log')
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest')
    )

def run_script(script_name, *args):
    """Pythonスクリプトをサブプロセスで実行"""
    script_path = os.path.join(SCRIPT_DIR, script_name)
    cmd = ['python3', script_path] + list(args)
    log.info(f"実行: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if result.stdout:
        for line in result.stdout.strip().split('\n'):
            log.info(f"  {line}")
    if result.stderr:
        for line in result.stderr.strip().split('\n'):
            if line.strip():
                log.warning(f"  [STDERR] {line}")
    if result.returncode != 0:
        log.error(f"  終了コード: {result.returncode}")
        return False
    log.info("  完了")
    return True

def task_scrape():
    log.info("=== タスク: 重賞結果スクレイピング ===")
    run_script('scraper.py', '1')

def task_analyze():
    log.info("=== タスク: 顔分析 ===")
    run_script('face_analyzer.py')

def task_entries():
    log.info("=== タスク: 出走馬自動取得 ===")
    run_script('entry_fetcher.py')

def task_record():
    """的中記録の自動取得"""
    log.info("=== タスク: 的中記録 自動取得 ===")
    run_script('result_auto_fetcher.py')

def task_notify():
    """
    直近レースの予想をLINEへ自動通知
    race_specific_result から今週末のレースを抽出して送信
    """
    log.info("=== タスク: LINE自動通知 ===")

    try:
        conn = get_conn()
        cur = conn.cursor()
        today = datetime.now().date()
        next_week = today + timedelta(days=7)

        # 直近7日以内の race_entry からレース名を取得
        cur.execute("""
            SELECT DISTINCT race_name, MIN(race_date) as race_date
            FROM race_entry
            WHERE race_date BETWEEN %s AND %s
            GROUP BY race_name
            ORDER BY race_date
        """, (today, next_week))
        upcoming = cur.fetchall()
        cur.close()
        conn.close()

        if not upcoming:
            log.info("  通知対象レースなし")
            return

        for race_name, race_date in upcoming:
            # race_specific_result に予想があるか確認
            conn2 = get_conn()
            cur2  = conn2.cursor()
            cur2.execute("""
                SELECT COUNT(*) FROM race_specific_result WHERE race_name = %s
            """, (race_name,))
            cnt = cur2.fetchone()[0]
            cur2.close()
            conn2.close()

            if cnt == 0:
                log.info(f"  {race_name}: 予想なし → スキップ")
                continue

            days_left = (race_date - today).days
            log.info(f"  通知: {race_name} ({race_date}、あと{days_left}日)")
            run_script('notifier.py', 'send-v2', race_name)
            time.sleep(2)

    except Exception as e:
        log.error(f"  通知エラー: {e}")

def task_all():
    log.info(f"=== 全タスク実行開始: {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    task_scrape()
    task_analyze()
    task_entries()
    task_record()
    log.info("=== 全タスク完了 ===")

def run_weekly_daemon():
    log.info("=== スケジューラー デーモン起動 ===")
    while True:
        now     = datetime.now()
        weekday = now.weekday()  # 0=月, 3=木, 4=金

        if weekday == 0 and now.hour == 6 and now.minute < 10:
            log.info("【月曜定期実行】スクレイピング＋顔分析＋的中記録")
            task_scrape()
            task_analyze()
            task_record()

        if weekday == 3 and now.hour == 6 and now.minute < 10:
            log.info("【木曜定期実行】出走馬取得")
            task_entries()

        if weekday == 4 and now.hour == 8 and now.minute < 10:
            log.info("【金曜定期実行】LINE自動通知")
            task_notify()

        time.sleep(600)  # 10分ごとにチェック

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    dispatch = {
        'weekly':  run_weekly_daemon,
        'scrape':  task_scrape,
        'analyze': task_analyze,
        'entries': task_entries,
        'record':  task_record,
        'notify':  task_notify,
        'all':     task_all,
    }
    fn = dispatch.get(cmd)
    if fn:
        fn()
    else:
        log.error(f"不明なコマンド: {cmd}")
        print("使い方: python scheduler.py [weekly|scrape|analyze|entries|record|notify|all]")

if __name__ == '__main__':
    main()
