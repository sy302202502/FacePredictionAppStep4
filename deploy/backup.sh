#!/usr/bin/env bash
# ============================================================
# backup.sh
# 日次バックアップ: PostgreSQL → OCI Object Storage (無料枠)
#
# 使い方（cron から実行）:
#   0 3 * * * ubuntu bash /opt/faceprediction/deploy/backup.sh
# ============================================================
set -euo pipefail

APP_DIR="/opt/faceprediction"
BACKUP_DIR="$APP_DIR/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/faceapp_$DATE.sql.gz"
KEEP_DAYS=7  # ローカルに保持する日数

# .env から DB情報を読み込む
source "$APP_DIR/.env" 2>/dev/null || true

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-faceapp}"
DB_USER="${DB_USER:-postgres}"
export PGPASSWORD="${DB_PASSWORD:-}"

mkdir -p "$BACKUP_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] バックアップ開始: $BACKUP_FILE"

# ── pg_dump ─────────────────────────────────────────────────
pg_dump \
  -h "$DB_HOST" \
  -p "$DB_PORT" \
  -U "$DB_USER" \
  -d "$DB_NAME" \
  --no-owner \
  --no-acl \
  | gzip > "$BACKUP_FILE"

SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 完了: $SIZE"

# ── 古いバックアップを削除 ────────────────────────────────────
find "$BACKUP_DIR" -name "faceapp_*.sql.gz" -mtime +"$KEEP_DAYS" -delete
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 古いバックアップ削除完了 (${KEEP_DAYS}日以前)"

# ── OCI Object Storage へアップロード（oci CLI インストール済みの場合） ─
# OCI_BUCKET="${OCI_BUCKET:-faceprediction-backups}"
# if command -v oci &>/dev/null; then
#   oci os object put \
#     --bucket-name "$OCI_BUCKET" \
#     --file "$BACKUP_FILE" \
#     --name "db/$(basename "$BACKUP_FILE")" \
#     --force
#   echo "[$(date '+%Y-%m-%d %H:%M:%S')] OCI Object Storage アップロード完了"
# fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] バックアップ正常終了"
