#!/usr/bin/env bash
# ============================================================
# setup_conoha_cron.sh
# ConoHa VPS にcron自動化を設定する
# 使い方: bash deploy/setup_conoha_cron.sh
# ============================================================
set -euo pipefail

APP_DIR="/opt/faceprediction"
echo "======================================================"
echo "  ConoHa cron 自動化セットアップ"
echo "======================================================"

# ── 1. タイムゾーンをJSTに ─────────────────────────────
echo ""
echo "[1/5] タイムゾーンをJSTに設定..."
timedatectl set-timezone Asia/Tokyo || echo "  (既に設定済みかも)"
echo "  → $(date)"

# ── 2. Pythonコンテナを常駐モードで再起動 ──────────────
echo ""
echo "[2/5] Pythonコンテナを常駐モードで起動..."
cd "$APP_DIR"
docker compose up -d python
sleep 3
if docker ps --format '{{.Names}}' | grep -q '^faceprediction-python$'; then
    echo "  ✓ Pythonコンテナ稼働中"
else
    echo "  ✗ Pythonコンテナが起動しない！"
    exit 1
fi

# ── 3. cron設定 ───────────────────────────────────────
echo ""
echo "[3/5] cron設定を登録..."
crontab "$APP_DIR/deploy/conoha_crontab.txt"
echo "  ✓ 登録完了"

# ── 4. テスト実行 ─────────────────────────────────────
echo ""
echo "[4/5] パイプライン疎通テスト（quickモード）..."
bash "$APP_DIR/deploy/conoha_pipeline.sh" quick > /tmp/cron_test.log 2>&1 &
sleep 3
if pgrep -f conoha_pipeline > /dev/null; then
    echo "  ✓ パイプライン起動成功（バックグラウンド実行中）"
fi

# ── 5. crontab確認 ────────────────────────────────────
echo ""
echo "[5/5] 登録されたcronスケジュール:"
crontab -l | grep -v "^#" | grep -v "^$" | head -10

echo ""
echo "======================================================"
echo "  ✅ セットアップ完了"
echo "======================================================"
echo ""
echo "次回実行予定:"
echo "  毎週金曜 8:00 → 全週末レース予想を自動生成"
echo "  毎週土日 17/19/22時 → レース結果を自動取得"
echo "  平日12:00 → オッズ更新"
echo ""
echo "確認コマンド:"
echo "  crontab -l                          # cron設定確認"
echo "  ls $APP_DIR/logs/conoha_*.log       # 実行ログ"
echo "  tail -f $APP_DIR/logs/conoha_*.log  # 実行中のログ"
