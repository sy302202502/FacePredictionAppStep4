#!/usr/bin/env bash
# ============================================================
# weekly_pipeline.sh
# 毎週土曜7時に自動実行される週次予想パイプライン
#
# launchdで登録: 
#   cp deploy/weekly_pipeline.sh /usr/local/bin/
#   launchctl load ~/Library/LaunchAgents/com.faceprediction.weekly.plist
# ============================================================
set -euo pipefail

APP_DIR="/Users/shibayuya/git/FacePredictionAppStep4"
LOG_DIR="$APP_DIR/logs"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$LOG_DIR"
exec >> "$LOG_DIR/weekly_$DATE.log" 2>&1

echo "======================================================"
echo "  週次予想パイプライン開始: $(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================================"

cd "$APP_DIR"
source .env 2>/dev/null || true

# Step1: 今週末のレース情報を取得
echo "[Step1] レースエントリー取得..."
python3 python/race_entry_fetcher.py 2>&1 | tail -5 || echo "  [警告] エントリー取得に失敗"

# Step2: オッズ取得
echo "[Step2] オッズ取得..."
python3 python/odds_fetcher.py 2>&1 | tail -5 || echo "  [警告] オッズ取得に失敗"

# Step3: 万馬券チャレンジ（高配当レース厳選）
echo "[Step3] 万馬券チャレンジ選定..."
python3 python/high_dividend_selector.py 2>&1 | tail -10 || echo "  [警告] 高配当選定に失敗"

# Step4: 重賞レース予想
echo "[Step4] 重賞レース予想..."
# DBから今週末の重賞レースを取得して予想
python3 - << 'PYEOF'
import psycopg2, os, subprocess, sys
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(
    host=os.getenv('DB_HOST','localhost'), port=os.getenv('DB_PORT','5432'),
    dbname=os.getenv('DB_NAME','faceapp'), user=os.getenv('DB_USER','postgres'),
    password=os.getenv('DB_PASSWORD','')
)
cur = conn.cursor()
cur.execute("""
    SELECT DISTINCT race_name FROM race_entry
    WHERE race_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '7 days'
      AND grade IN ('G1','G2','G3','OP')
    ORDER BY race_name
""")
races = [r[0] for r in cur.fetchall()]
conn.close()
if not races:
    print("  重賞レースなし")
    sys.exit(0)
for race in races:
    print(f"  予想実行: {race}")
    subprocess.run(['python3', 'python/race_specific_analyzer.py', race], timeout=600)
PYEOF

# Step4.5: レース名整合性チェック・自動修正・未予想を自動予想
echo "[Step4.5] レース名整合性チェック..."
python3 python/race_name_reconciler.py --apply --predict 2>&1 | tail -10 || echo "  [警告] 整合性チェック失敗"

# Step5: バックアップ
echo "[Step5] DBバックアップ..."
mkdir -p "$APP_DIR/backups"
PGPASSWORD="$DB_PASSWORD" pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    --no-owner --no-acl | gzip > "$APP_DIR/backups/faceapp_$(date +%Y%m%d).sql.gz"
find "$APP_DIR/backups" -name "*.sql.gz" -mtime +7 -delete
echo "  バックアップ完了"

echo "======================================================"
echo "  週次パイプライン完了: $(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================================"
