"""
cleanup_uploads.py — uploads/ の古い画像を整理するGCスクリプト

【対象と方針】
  - race_specific/ : レガシー分析用の過去馬写真。netkeibaから再取得可能なキャッシュなので
                     更新から DAYS_RACE_SPECIFIC 日を超えたものを削除対象にする。
  - paddock/       : パドック分析の一時アップロード。DAYS_PADDOCK 日で削除対象。
  - candidates/ , horses/ : 現行システムが表示・分析に使うため対象外（削除しない）。

【安全設計】
  - 既定はドライラン（削除対象の一覧と合計サイズを表示するだけ）。--apply で実際に削除。
  - ディレクトリ自体や対象外ディレクトリには一切触れない。

使い方:
  python3 python/cleanup_uploads.py            # ドライラン
  python3 python/cleanup_uploads.py --apply    # 削除実行
  （VPS: docker compose exec python python3 python/cleanup_uploads.py --apply）

cron化する場合（VPS・任意）:
  0 5 * * 1  cd /opt/faceprediction && docker compose exec -T python python3 python/cleanup_uploads.py --apply >> logs/cleanup.log 2>&1
"""
from __future__ import annotations

import os
import sys
import time

UPLOAD_DIR = os.getenv('UPLOAD_DIR', os.path.join(os.path.dirname(__file__), '../uploads'))
DAYS_RACE_SPECIFIC = int(os.getenv('GC_DAYS_RACE_SPECIFIC', '180'))
DAYS_PADDOCK       = int(os.getenv('GC_DAYS_PADDOCK', '30'))

TARGETS = [
    ('race_specific', DAYS_RACE_SPECIFIC),
    ('paddock',       DAYS_PADDOCK),
]


def main():
    apply = '--apply' in sys.argv
    mode = '【削除実行】' if apply else '【ドライラン】'
    now = time.time()
    print(f"=== uploads GC {mode} 基点: {os.path.abspath(UPLOAD_DIR)} ===")

    total_n = total_b = 0
    for sub, days in TARGETS:
        d = os.path.join(UPLOAD_DIR, sub)
        if not os.path.isdir(d):
            print(f"[{sub}] ディレクトリなし → スキップ")
            continue
        cutoff = now - days * 86400
        victims = []
        for name in os.listdir(d):
            p = os.path.join(d, name)
            if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                victims.append((p, os.path.getsize(p)))
        size_mb = sum(b for _, b in victims) / 1e6
        print(f"[{sub}] {days}日超のファイル: {len(victims)}件 / {size_mb:.1f}MB")
        if apply:
            for p, _ in victims:
                try:
                    os.remove(p)
                except OSError as e:
                    print(f"  [警告] 削除失敗: {p}: {e}")
            print(f"  → 削除完了")
        total_n += len(victims)
        total_b += sum(b for _, b in victims)

    print(f"\n合計: {total_n}件 / {total_b/1e6:.1f}MB {'を削除しました' if apply else 'が削除対象（--apply で実行）'}")


if __name__ == '__main__':
    main()
