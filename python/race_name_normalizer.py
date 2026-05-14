"""
race_name_normalizer.py
entry_fetcher保存後にレース名の切り詰めを自動修正するスクリプト

【問題】
  netkeibaの出馬表ページで一部レース名が切り詰められて保存される:
    "ヴィクトリアマイル" → "ヴィクトリア"
    "BSイレブン賞"      → "BSイレブン"
  この場合、race_specific_predictionのレース名と一致せず予想ページに表示されない。

【解決策】
  既知の権威データ（grade_race_result, 過去のrace_entry完全名）と照合して
  race_entryのレース名を自動補正する。

使い方:
  python3 python/race_name_normalizer.py                  # ドライラン
  python3 python/race_name_normalizer.py --apply          # 実行
  python3 python/race_name_normalizer.py --apply --date 2026-05-17
"""

import os
import sys
import psycopg2
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)


def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest'),
    )


def collect_authoritative_names(conn):
    """権威データから完全なレース名一覧を取得"""
    cur = conn.cursor()
    names = set()

    # grade_race_resultは完全名で保存されている
    cur.execute("SELECT DISTINCT race_name FROM grade_race_result WHERE race_name IS NOT NULL")
    for (n,) in cur.fetchall():
        if n:
            names.add(n)

    # race_specific_predictionにある名前も信頼できる
    cur.execute("SELECT DISTINCT race_name FROM race_specific_prediction WHERE race_name IS NOT NULL")
    for (n,) in cur.fetchall():
        if n:
            names.add(n)

    # ※ race_entryは権威データに含めない（自分自身が切り詰められている可能性があるため）

    cur.close()
    return names


def find_truncation(short: str, authoritative: set[str]) -> str | None:
    """短い名前が他の完全名の prefix になっているか調べ、最も長い候補を返す"""
    if not short:
        return None
    candidates = []
    for full in authoritative:
        if full == short:
            return None  # 既に完全名
        if full.startswith(short) and len(full) > len(short):
            # 切り詰めが妥当な範囲か（5文字以内の追加なら妥当）
            extra = full[len(short):]
            if 1 <= len(extra) <= 6:
                # 末尾が「マイル」「賞」「C」「S」「カップ」など典型語尾なら確信
                if extra in ('マイル', '賞', 'C', 'S', 'カップ', 'ステークス',
                              'チャンピオンシップ', 'ターフ', 'マイラーズ',
                              '記念', '杯', '優駿', 'ジョッキー', 'ダービー'):
                    return full
                candidates.append(full)
    # 典型語尾でなければ、最も短い追加で済む候補を採用
    if candidates:
        candidates.sort(key=len)
        return candidates[0]
    return None


def main():
    apply = '--apply' in sys.argv
    date_from = date.today()
    date_to = date_from + timedelta(days=14)

    if '--date' in sys.argv:
        idx = sys.argv.index('--date')
        if idx + 1 < len(sys.argv):
            date_from = datetime.strptime(sys.argv[idx + 1], '%Y-%m-%d').date()
            date_to = date_from + timedelta(days=1)

    print("=" * 60)
    print(f"  レース名正規化 ({date_from} 〜 {date_to})")
    print(f"  モード: {'実行' if apply else 'ドライラン'}")
    print("=" * 60)

    conn = get_conn()
    authoritative = collect_authoritative_names(conn)
    print(f"  権威データから {len(authoritative)} 件のレース名を読み込み")

    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT race_name, race_date
        FROM race_entry
        WHERE race_date BETWEEN %s AND %s
        ORDER BY race_date, race_name
        """,
        (date_from, date_to),
    )
    entries = cur.fetchall()

    found = 0
    fixed = 0
    for race_name, race_date in entries:
        full = find_truncation(race_name, authoritative)
        if full:
            found += 1
            print(f"  🔧 {race_date} '{race_name}' → '{full}'")
            if apply:
                cur.execute(
                    "UPDATE race_entry SET race_name = %s WHERE race_name = %s AND race_date = %s",
                    (full, race_name, race_date),
                )
                fixed += 1

    if apply:
        conn.commit()
    cur.close()
    conn.close()

    print("=" * 60)
    print(f"  切り詰め検出: {found} 件")
    if apply:
        print(f"  修正完了    : {fixed} 件")
    else:
        if found > 0:
            print("  💡 修正するには --apply を付けて再実行")
    print("=" * 60)


if __name__ == '__main__':
    main()
