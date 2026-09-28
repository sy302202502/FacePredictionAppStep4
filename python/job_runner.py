"""
job_runner.py — cron ジョブの実行履歴を job_run テーブルに記録するラッパー

  python3 python/job_runner.py <ジョブ名> <スクリプト.py> [引数...]
  例: python3 python/job_runner.py pipeline weekly_pipeline.py
  ジョブ名は英字キー（pipeline / sync / odds / results / cleanup）。日本語表記は画面側で付ける

・子スクリプトの出力はそのまま標準出力へ流す（cron のログファイルは従来どおり）
・開始/終了時刻・終了コード・最後の RESULT 行（無ければ末尾の1行）を記録する
・DB に書けなくてもジョブ自体は必ず実行し、子の終了コードを返す
  （3時間で打ち切りは 124、シグナル終了は 128+番号）
・管理画面 /jobs で一覧できる
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from collections import deque

import psycopg2
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

TIMEOUT_SEC = 3 * 60 * 60   # 3時間で打ち切る（ハングしたジョブが次回と重ならないように）


def _conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'), user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest'),
        connect_timeout=int(os.getenv('PGCONNECT_TIMEOUT', '15')),
        options='-c statement_timeout=30000')


def _start(job, command):
    try:
        conn = _conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS job_run (
                id          SERIAL PRIMARY KEY,
                job_name    VARCHAR(50) NOT NULL,
                command     VARCHAR(300),
                started_at  TIMESTAMP DEFAULT NOW(),
                finished_at TIMESTAMP,
                exit_code   INTEGER,
                summary     TEXT
            )
        """)
        cur.execute("INSERT INTO job_run (job_name, command) VALUES (%s, %s) RETURNING id",
                    (job, command[:300]))
        run_id = cur.fetchone()[0]
        conn.close()
        return run_id
    except Exception as e:
        print(f"[job_runner] 開始記録に失敗（ジョブは実行します）: {e}", flush=True)
        return None


def _finish(run_id, exit_code, summary):
    if run_id is None:
        return
    try:
        conn = _conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("UPDATE job_run SET finished_at = NOW(), exit_code = %s, summary = %s WHERE id = %s",
                    (exit_code, (summary or '')[:1000], run_id))
        # 履歴は直近180日分だけ残す
        cur.execute("DELETE FROM job_run WHERE started_at < NOW() - INTERVAL '180 days'")
        conn.close()
    except Exception as e:
        print(f"[job_runner] 終了記録に失敗: {e}", flush=True)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    job, script, args = sys.argv[1], sys.argv[2], sys.argv[3:]
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), script)
    cmd = [sys.executable, path] + args
    run_id = _start(job, ' '.join([script] + args))

    tail = deque(maxlen=40)
    state = {'result': None}

    def pump(stream):
        # 出力の転送は別スレッドで行い、本体は wait(timeout) で期限を監視する
        # （本体で readline を回すと、子が黙ったままハングしたときに期限が効かない）
        for line in stream:
            sys.stdout.write(line)
            sys.stdout.flush()
            line = line.rstrip()
            if line:
                tail.append(line)
            if 'RESULT:' in line:
                state['result'] = line.strip()

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, bufsize=1, start_new_session=True)
        reader = threading.Thread(target=pump, args=(proc.stdout,), daemon=True)
        reader.start()
        try:
            rc = proc.wait(timeout=TIMEOUT_SEC)
            # シグナルで落ちた子（rc<0）はシェルの慣例どおり 128+シグナル番号にする
            exit_code = rc if rc >= 0 else 128 - rc
        except subprocess.TimeoutExpired:
            # 子が起動した孫プロセスごと止める（TERM → 猶予 → KILL）
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(proc.pid, sig)
                    proc.wait(timeout=15)
                    break
                except (subprocess.TimeoutExpired, ProcessLookupError):
                    continue
            exit_code = 124  # timeout(1) と同じ慣例
            tail.append(f"タイムアウト（{TIMEOUT_SEC // 60}分）で打ち切り")
        reader.join(timeout=5)
    except Exception as e:
        exit_code = 1
        tail.append(f"起動失敗: {e}")
    result_line = state['result']

    summary = result_line or (tail[-1] if tail else '')
    if exit_code != 0 and tail:
        # 失敗時は原因を追えるよう末尾数行を残す
        summary = '\n'.join(list(tail)[-8:])
    _finish(run_id, exit_code, summary)
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
