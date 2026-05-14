#!/usr/bin/env bash
# ============================================================
# migrate_to_supabase.sh
# ローカル PostgreSQL → Supabase へデータを移行する
#
# 使い方:
#   export SUPABASE_DB_URL="postgresql://postgres:[password]@db.[ref].supabase.co:5432/postgres"
#   bash deploy/migrate_to_supabase.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# ── 設定 ─────────────────────────────────────────────────────
LOCAL_DB="${LOCAL_DB:-faceapp}"
REMOTE_URL="${SUPABASE_DB_URL:?'SUPABASE_DB_URL が未設定です。export してから実行してください。'}"

echo "======================================================"
echo "  Supabase 移行スクリプト"
echo "  Local DB : $LOCAL_DB"
echo "  Remote   : $(echo "$REMOTE_URL" | sed 's/:.*@/:****@/')"
echo "======================================================"

# ── Step1: スキーマを Supabase に適用 ─────────────────────────
echo ""
echo "[Step1] スキーマを適用中..."
psql "$REMOTE_URL" -f "$SCRIPT_DIR/schema.sql" -q
echo "  → スキーマ適用 完了"

# ── Step2: データをダンプ → リストア ─────────────────────────
echo ""
echo "[Step2] データを移行中..."

TABLES=(
  horse_face_feature
  race_specific_prediction
  race_specific_result
  race_entry
  race_odds
  stats_prediction
  grade_race_result
  high_dividend_selection
  race_specific_accuracy
  prediction_result
  prediction_accuracy
  face_image
  races
)

for TABLE in "${TABLES[@]}"; do
  COUNT=$(psql "$LOCAL_DB" -tAc "SELECT COUNT(*) FROM $TABLE" 2>/dev/null || echo 0)
  if [ "$COUNT" -gt 0 ]; then
    printf "  %-35s %6d 件..." "$TABLE" "$COUNT"
    pg_dump "$LOCAL_DB" \
      --data-only \
      --no-owner \
      --no-acl \
      --disable-triggers \
      --table="$TABLE" \
      2>/dev/null \
    | grep -v "^\\\\" \
    | psql "$REMOTE_URL" -q
    echo " OK"
  else
    printf "  %-35s %6s 件  (スキップ)\n" "$TABLE" "0"
  fi
done

# ── Step3: シーケンスをリセット ───────────────────────────────
echo ""
echo "[Step3] シーケンスをリセット中..."
psql "$REMOTE_URL" -q <<'SQL'
DO $$
DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT sequence_name,
           replace(sequence_name, '_id_seq', '') AS tbl
    FROM information_schema.sequences
    WHERE sequence_schema = 'public'
  LOOP
    BEGIN
      EXECUTE format(
        'SELECT setval(%L, COALESCE((SELECT MAX(id) FROM %I), 1))',
        r.sequence_name, r.tbl
      );
    EXCEPTION WHEN OTHERS THEN NULL;
    END;
  END LOOP;
END $$;
SQL
echo "  → シーケンスリセット 完了"

echo ""
echo "======================================================"
echo "  移行完了！"
echo "  Supabase の接続情報を .env に設定してください:"
echo ""
echo "  DB_HOST=db.[ref].supabase.co"
echo "  DB_PORT=5432"
echo "  DB_NAME=postgres"
echo "  DB_USER=postgres"
echo "  DB_PASSWORD=[your-password]"
echo "======================================================"
