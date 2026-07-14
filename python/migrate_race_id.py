"""
migrate_race_id.py
stats_prediction / race_specific_accuracy に race_id 列を追加して backfill する移行スクリプト。

【背景】
  両テーブルは race_name（+horse_name）でしか開催を識別できず、
  年またぎ同名レース・表記揺れ・重複行など多くの不具合の根本原因だった。
  race_id を持たせ、以後の突合・削除・集計を race_id 基準にする。

【安全設計】
  - 追加は nullable 列 + 部分UNIQUEインデックスのみ（旧コードはそのまま動く）
  - 既定はドライラン。--apply で実行
  - backfill は「同じ horse_id×race_name で、race_date が created_at に最も近い開催」を採用
    （年またぎを正しく解決）。一致しない行は NULL のまま残す（削除しない）
  - 再実行可能（IF NOT EXISTS / race_id IS NULL のみ対象）

使い方:
  python3 python/migrate_race_id.py           # ドライラン（件数レポートのみ）
  python3 python/migrate_race_id.py --apply   # 実行
"""
from __future__ import annotations

import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)


def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'), user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD') or sys.exit('[エラー] DB_PASSWORD 未設定'),
        connect_timeout=int(os.getenv('PGCONNECT_TIMEOUT', '15')),
        options='-c statement_timeout=120000'
    )


def main():
    apply = '--apply' in sys.argv
    mode = '【実行】' if apply else '【ドライラン】'
    print(f"=== race_id 移行 {mode} ===\n")

    conn = get_conn()
    cur = conn.cursor()
    try:
        # ── 1. 列追加（nullable。旧コードに影響なし）─────────────────
        print("[1] race_id 列の追加")
        cur.execute("ALTER TABLE stats_prediction ADD COLUMN IF NOT EXISTS race_id VARCHAR(20)")
        cur.execute("ALTER TABLE race_specific_accuracy ADD COLUMN IF NOT EXISTS race_id VARCHAR(20)")
        print("  ✓ ALTER（IF NOT EXISTS）")

        # ── 2. stats_prediction backfill ────────────────────────────
        # horse_id × race_name 一致のうち race_date が created_at に最も近い開催を採用
        print("\n[2] stats_prediction の backfill")
        cur.execute("""
            SELECT COUNT(*) FROM stats_prediction WHERE race_id IS NULL
        """)
        before_null = cur.fetchone()[0]
        cur.execute("""
            UPDATE stats_prediction sp
            SET race_id = best.race_id
            FROM (
                SELECT DISTINCT ON (sp2.id) sp2.id, re.race_id
                FROM stats_prediction sp2
                JOIN race_entry re
                  ON re.horse_id = sp2.horse_id
                 AND re.race_name = sp2.race_name
                WHERE sp2.race_id IS NULL AND sp2.horse_id IS NOT NULL
                ORDER BY sp2.id,
                         ABS(EXTRACT(EPOCH FROM (re.race_date::timestamp - sp2.created_at)))
            ) best
            WHERE sp.id = best.id
        """)
        filled1 = cur.rowcount
        # 第2パス: race_name 不一致（scraped_name 等）でも、開催日が近い一意候補で補完
        cur.execute("""
            UPDATE stats_prediction sp
            SET race_id = best.race_id
            FROM (
                SELECT DISTINCT ON (sp2.id) sp2.id, re.race_id
                FROM stats_prediction sp2
                JOIN race_entry re
                  ON re.horse_id = sp2.horse_id
                 AND re.race_date BETWEEN (sp2.created_at::date - 10) AND (sp2.created_at::date + 10)
                WHERE sp2.race_id IS NULL AND sp2.horse_id IS NOT NULL
                ORDER BY sp2.id,
                         ABS(EXTRACT(EPOCH FROM (re.race_date::timestamp - sp2.created_at)))
            ) best
            WHERE sp.id = best.id
        """)
        filled2 = cur.rowcount
        cur.execute("SELECT COUNT(*) FROM stats_prediction WHERE race_id IS NULL")
        after_null = cur.fetchone()[0]
        print(f"  対象 {before_null} 行 → 名前一致で {filled1} 行 / 日付近傍で {filled2} 行を補完"
              f" / 未解決 {after_null} 行（NULLのまま保持）")

        # ── 3. 重複解消（同一 race_id×horse_id は顔面データ優先→新しい行を残す）──
        print("\n[3] (race_id, horse_id) 重複の解消")
        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT race_id, horse_id FROM stats_prediction
                WHERE race_id IS NOT NULL AND horse_id IS NOT NULL
                GROUP BY race_id, horse_id HAVING COUNT(*) > 1
            ) d
        """)
        dup_groups = cur.fetchone()[0]
        cur.execute("""
            DELETE FROM stats_prediction sp
            USING (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY race_id, horse_id
                    ORDER BY (face_comment IS NOT NULL) DESC, created_at DESC, id DESC
                ) AS rn
                FROM stats_prediction
                WHERE race_id IS NOT NULL AND horse_id IS NOT NULL
            ) ranked
            WHERE sp.id = ranked.id AND ranked.rn > 1
        """)
        deleted = cur.rowcount
        print(f"  重複グループ {dup_groups} 件 → {deleted} 行削除（顔面データ有り・新しい行を優先残置）")

        # ── 4. インデックス/一意制約 ────────────────────────────────
        print("\n[4] インデックス作成")
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_stats_prediction_race_horse
            ON stats_prediction(race_id, horse_id)
            WHERE race_id IS NOT NULL AND horse_id IS NOT NULL
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_stats_prediction_race_id ON stats_prediction(race_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_rsa_race_id ON race_specific_accuracy(race_id)")
        print("  ✓ 部分UNIQUE(race_id, horse_id) + race_id インデックス")

        # ── 5. race_specific_accuracy backfill（horse_name 突合・ベストエフォート）──
        print("\n[5] race_specific_accuracy の backfill")
        cur.execute("SELECT COUNT(*) FROM race_specific_accuracy WHERE race_id IS NULL")
        rsa_before = cur.fetchone()[0]
        cur.execute("""
            UPDATE race_specific_accuracy rsa
            SET race_id = best.race_id
            FROM (
                SELECT DISTINCT ON (rsa2.id) rsa2.id, re.race_id
                FROM race_specific_accuracy rsa2
                JOIN race_entry re
                  ON re.race_name = rsa2.race_name
                 AND re.horse_name = rsa2.horse_name
                WHERE rsa2.race_id IS NULL
                ORDER BY rsa2.id,
                         ABS(EXTRACT(EPOCH FROM (re.race_date::timestamp - rsa2.recorded_at)))
            ) best
            WHERE rsa.id = best.id
        """)
        rsa_filled = cur.rowcount
        cur.execute("SELECT COUNT(*) FROM race_specific_accuracy WHERE race_id IS NULL")
        rsa_after = cur.fetchone()[0]
        print(f"  対象 {rsa_before} 行 → {rsa_filled} 行補完 / 未解決 {rsa_after} 行")

        # ── 6. 検証サマリ ───────────────────────────────────────────
        print("\n[6] 検証")
        cur.execute("""
            SELECT COUNT(*),
                   COUNT(race_id),
                   COUNT(*) FILTER (WHERE race_id IS NULL AND created_at > NOW() - INTERVAL '45 days')
            FROM stats_prediction
        """)
        total, with_id, recent_null = cur.fetchone()
        print(f"  stats_prediction: 全{total}行 / race_id付き {with_id} / 直近45日でNULL {recent_null}")
        if recent_null > 0:
            print("  ⚠️ 直近データに未解決行があります。要確認。")

        if apply:
            conn.commit()
            print(f"\n✅ 移行をコミットしました")
        else:
            conn.rollback()
            print(f"\n（ドライラン: すべてロールバックしました。実行は --apply）")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
