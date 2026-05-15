#!/usr/bin/env bash
# ============================================================
# conoha_pipeline.sh
# ConoHa VPS上で動く週次予想パイプライン
# Pythonコンテナにexecして各スクリプトを実行
# ============================================================
set -euo pipefail

APP_DIR="/opt/faceprediction"
LOG_DIR="$APP_DIR/logs"
PYC="faceprediction-python"   # Pythonコンテナ名
MODE="${1:-weekly}"            # weekly / results / quick
DATE=$(date '+%Y%m%d_%H%M%S')

mkdir -p "$LOG_DIR"
exec >> "$LOG_DIR/conoha_${MODE}_${DATE}.log" 2>&1

echo "======================================================"
echo "  [$(date '+%Y-%m-%d %H:%M:%S')] ConoHa Pipeline START (mode=$MODE)"
echo "======================================================"

cd "$APP_DIR"

# Pythonコンテナが起動していなければ起動
if ! docker ps --format '{{.Names}}' | grep -q "^${PYC}$"; then
    echo "[起動] Pythonコンテナを起動..."
    docker compose up -d python
    sleep 5
fi

run_py() {
    local script="$1"; shift
    echo ""
    echo "[実行] python/$script $@"
    docker exec "$PYC" python3 "/app/python/$script" "$@" 2>&1 | tail -50 || echo "  [警告] $script 失敗"
}

case "$MODE" in
    weekly)
        # ── 金曜朝に実行：今週末レースの完全準備 ──
        echo "[Step1] エントリー取得 + 名前正規化"
        run_py entry_fetcher.py

        echo "[Step2] オッズ取得"
        run_py odds_fetcher.py || true

        echo "[Step3] 万馬券チャレンジ選定"
        run_py high_dividend_selector.py || true

        echo "[Step4] 重賞レース予想"
        docker exec "$PYC" python3 -c "
import psycopg2, os, subprocess, sys
from datetime import date, timedelta
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'), port=os.getenv('DB_PORT','5432'),
    dbname=os.getenv('DB_NAME'), user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'))
cur = conn.cursor()
cur.execute(\"\"\"
    SELECT DISTINCT race_name FROM race_entry
    WHERE race_date BETWEEN (NOW() AT TIME ZONE 'Asia/Tokyo')::date
                        AND (NOW() AT TIME ZONE 'Asia/Tokyo')::date + INTERVAL '7 days'
      AND (grade IN ('G1','G2','G3','OP') OR race_name LIKE '%S' OR race_name LIKE '%賞' OR race_name LIKE '%C')
    ORDER BY race_name
\"\"\")
races = [r[0] for r in cur.fetchall()]
conn.close()
print(f'  対象レース: {len(races)}件')
for race in races:
    print(f'  予想実行: {race}')
    r = subprocess.run(['python3', '/app/python/race_specific_analyzer.py', race],
                       timeout=1800, capture_output=True, text=True)
    # 結果の最後だけ表示
    for line in (r.stdout or '').splitlines()[-3:]:
        print(f'    {line}')
" 2>&1 | tail -100
        ;;

    results)
        # ── 土・日の夕方〜夜：レース結果取得 ──
        echo "[Step1] レース結果自動取得"
        run_py result_auto_fetcher.py
        ;;

    quick)
        # ── 任意のタイミング：エントリーとオッズだけ更新 ──
        echo "[Step1] エントリー取得"
        run_py entry_fetcher.py
        echo "[Step2] オッズ取得"
        run_py odds_fetcher.py || true
        ;;

    odds)
        # ── レース当日（土日）：オッズだけ更新（軽量・短時間） ──
        echo "[Step1] オッズ取得"
        run_py odds_fetcher.py
        ;;

    *)
        echo "Unknown mode: $MODE"
        exit 1
        ;;
esac

echo ""
echo "======================================================"
echo "  [$(date '+%Y-%m-%d %H:%M:%S')] ConoHa Pipeline END (mode=$MODE)"
echo "======================================================"

# 古いログを削除（30日以前）
find "$LOG_DIR" -name "conoha_*.log" -mtime +30 -delete 2>/dev/null || true
