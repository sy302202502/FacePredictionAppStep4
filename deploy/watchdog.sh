#!/usr/bin/env bash
# ============================================================
# watchdog.sh
# Spring Bootアプリのヘルスチェック＆ハング検出
# launchd の KeepAlive はクラッシュには対応するが、ハング（応答なし）には未対応
# このスクリプトが /actuator/health をチェックし、応答がなければプロセスを kill する
# （killされたあとlaunchdが自動再起動する）
#
# launchdで5分ごとに実行されるよう登録される
# ============================================================
set -u

HEALTH_URL="http://localhost:8081/actuator/health"
LOG_FILE="/Users/shibayuya/git/FacePredictionAppStep4/logs/watchdog.log"
TIMEOUT=10  # 10秒以内に応答がなければハングとみなす
PORT=8081

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

# ヘルスチェック
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" --max-time $TIMEOUT "$HEALTH_URL" 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
    # 正常 - 何もしない（静かに終了）
    exit 0
fi

log "❌ ヘルスチェック失敗 (HTTP=$HTTP_CODE) — ハングまたは未起動"

# 8081を掴んでいるプロセスを kill
PID=$(lsof -ti :$PORT 2>/dev/null || true)
if [ -n "$PID" ]; then
    log "🔪 ハングプロセスを kill: PID=$PID"
    kill -9 "$PID" 2>/dev/null || true
    # launchd の KeepAlive が自動再起動してくれる
fi
exit 0
