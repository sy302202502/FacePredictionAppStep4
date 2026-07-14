#!/bin/bash
# vps_backup.sh — 本番DB（VPS内 faceprediction-db コンテナ）の日次バックアップ
#
# DB統一（2026-07-14: 本番=VPSコンテナDB に一本化）に伴い、本番DBの唯一の
# バックアップ経路となるため cron で毎日実行する。
#
# セットアップ（VPSで1回だけ）:
#   chmod +x /opt/faceprediction/deploy/vps_backup.sh
#   (crontab -l; echo '0 4 * * * /opt/faceprediction/deploy/vps_backup.sh >> /opt/faceprediction/logs/backup.log 2>&1') | crontab -
#
# リストア例:
#   gunzip -c backups/db_YYYY-MM-DD.sql.gz | docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"'

set -u
set -o pipefail  # pg_dump の失敗を gzip の成功で握り潰さない
APP_DIR="/opt/faceprediction"
BACKUP_DIR="$APP_DIR/backups"
KEEP_DAYS=14
MIN_BYTES=100000  # これ未満のダンプは「中身が無い」とみなして失敗扱い（誤検知防止の下限）

mkdir -p "$BACKUP_DIR"
cd "$APP_DIR"

STAMP=$(date +%F)
OUT="$BACKUP_DIR/db_${STAMP}.sql.gz"

echo "[$(date '+%F %T')] バックアップ開始 → $OUT"
# アプリが実際に使うDB（.env の DB_HOST/DB_NAME）を python コンテナ経由でダンプする。
# db コンテナ直ダンプだと、DB_HOST が db 以外を指している構成で「空のDB」を保存してしまう。
if ! docker compose exec -T python sh -c \
    'PGPASSWORD="$DB_PASSWORD" pg_dump -h "$DB_HOST" -p "${DB_PORT:-5432}" -U "$DB_USER" "$DB_NAME"' \
    | gzip > "$OUT"; then
    echo "[$(date '+%F %T')] ❌ バックアップ失敗（pg_dump エラー）" >&2
    rm -f "$OUT"
    exit 1
fi
BYTES=$(stat -c%s "$OUT" 2>/dev/null || stat -f%z "$OUT")
if [ "$BYTES" -lt "$MIN_BYTES" ]; then
    echo "[$(date '+%F %T')] ❌ ダンプが小さすぎます (${BYTES}B < ${MIN_BYTES}B)。接続先DBが空の可能性。ファイルは残すが失敗扱い" >&2
    exit 1
fi
SIZE=$(du -h "$OUT" | cut -f1)
echo "[$(date '+%F %T')] 完了 ($SIZE)"

# 古い世代を削除（KEEP_DAYS 日より古いもの）
find "$BACKUP_DIR" -name 'db_*.sql.gz' -mtime +$KEEP_DAYS -delete
echo "[$(date '+%F %T')] 世代整理完了（保持 ${KEEP_DAYS} 日）"
