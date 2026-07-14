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
APP_DIR="/opt/faceprediction"
BACKUP_DIR="$APP_DIR/backups"
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR"
cd "$APP_DIR"

STAMP=$(date +%F)
OUT="$BACKUP_DIR/db_${STAMP}.sql.gz"

echo "[$(date '+%F %T')] バックアップ開始 → $OUT"
if docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$OUT"; then
    SIZE=$(du -h "$OUT" | cut -f1)
    echo "[$(date '+%F %T')] 完了 ($SIZE)"
else
    echo "[$(date '+%F %T')] ❌ バックアップ失敗" >&2
    rm -f "$OUT"
    exit 1
fi

# 古い世代を削除（KEEP_DAYS 日より古いもの）
find "$BACKUP_DIR" -name 'db_*.sql.gz' -mtime +$KEEP_DAYS -delete
echo "[$(date '+%F %T')] 世代整理完了（保持 ${KEEP_DAYS} 日）"
