"""
race_name_reconciler.py
レース名の不一致を自動検出・修正するスクリプト

機能:
  1. race_entry と race_specific_prediction のレース名を比較
  2. 表示できないレース（未予想 or 名前不一致）を検出
  3. 名前不一致は予想テーブル側を自動リネーム（fuzzy match）
  4. 未予想のレースは race_specific_analyzer.py を呼び出して予想実行

使い方:
  python3 python/race_name_reconciler.py                # ドライラン（検出のみ）
  python3 python/race_name_reconciler.py --apply        # 自動修正実行
  python3 python/race_name_reconciler.py --apply --predict  # 未予想も自動予想
  python3 python/race_name_reconciler.py --date 2026-05-16  # 日付絞り込み
"""

import os
import sys
import re
import subprocess
import psycopg2
from datetime import date, timedelta, datetime
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)


def get_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'faceapp'),
        user=os.getenv('DB_USER', 'postgres'),
        password=os.getenv('DB_PASSWORD', 'postgrestest'),
    )


# ──────────────────────────────────────────────
# レース名正規化（比較用）
# ──────────────────────────────────────────────

# 削除する語尾（マイル、賞、C、S など）
SUFFIX_RE = re.compile(r'(賞|C|S|G|HJ|マイル|ステークス|カップ)$')
# 削除する記号
SYMBOL_RE = re.compile(r'[（()【】[\]・\s]+')


def normalize(name: str) -> str:
    """レース名を比較しやすい形に正規化"""
    if not name:
        return ''
    n = SYMBOL_RE.sub('', name)
    # 末尾の修飾語を最大2回まで剥がす
    for _ in range(2):
        new_n = SUFFIX_RE.sub('', n)
        if new_n == n:
            break
        n = new_n
    return n


def similarity_score(a: str, b: str) -> float:
    """0-1のレース名類似度（正規化後の前方一致率）"""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # どちらかがもう一方を含む（切り詰めパターン）
    if na in nb or nb in na:
        short = min(len(na), len(nb))
        long_ = max(len(na), len(nb))
        return short / long_
    # 前方一致率
    common = 0
    for ca, cb in zip(na, nb):
        if ca == cb:
            common += 1
        else:
            break
    base_len = min(len(na), len(nb))
    return common / base_len if base_len > 0 else 0.0


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────

def find_mismatches(conn, date_from: date, date_to: date):
    """期間内の race_entry と prediction の不一致を検出"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT race_date, race_name
        FROM race_entry
        WHERE race_date BETWEEN %s AND %s
        ORDER BY race_date, race_name
        """,
        (date_from, date_to),
    )
    entries = cur.fetchall()

    cur.execute(
        """
        SELECT race_name, total_horses, confidence_level
        FROM race_specific_prediction
        WHERE analyzed_at >= %s
        """,
        (date_from - timedelta(days=14),),
    )
    predictions = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    cur.close()

    result = []
    for race_date, race_name in entries:
        if race_name in predictions:
            horses, conf = predictions[race_name]
            status = 'OK' if horses > 0 else 'NO_HORSES'
            result.append((race_date, race_name, status, race_name, horses))
            continue

        # fuzzy match: 類似度0.7以上で最大スコアのものを採用
        best_match = None
        best_score = 0.0
        for pname in predictions.keys():
            s = similarity_score(race_name, pname)
            if s > best_score:
                best_score = s
                best_match = pname

        if best_match and best_score >= 0.7:
            horses, _ = predictions[best_match]
            result.append((race_date, race_name, 'MISMATCH', best_match, horses))
        else:
            result.append((race_date, race_name, 'NOT_PREDICTED', None, 0))

    return result


def fix_mismatch(conn, entry_name: str, pred_name: str):
    """予想テーブル側のレース名をエントリー側に合わせる"""
    cur = conn.cursor()
    cur.execute("UPDATE race_specific_prediction SET race_name = %s WHERE race_name = %s", (entry_name, pred_name))
    cur.execute("UPDATE race_specific_result SET race_name = %s WHERE race_name = %s", (entry_name, pred_name))
    conn.commit()
    cur.close()


def run_prediction(race_name: str) -> bool:
    """race_specific_analyzer.py を呼んで予想を実行"""
    script = os.path.join(os.path.dirname(__file__), 'race_specific_analyzer.py')
    print(f"    → 予想実行中: {race_name}")
    try:
        r = subprocess.run(
            ['python3', script, race_name],
            timeout=900,
            capture_output=True,
            text=True,
        )
        ok = r.returncode == 0
        if not ok:
            print(f"    ✗ 終了コード {r.returncode}")
        return ok
    except subprocess.TimeoutExpired:
        print("    ✗ タイムアウト（15分超過）")
        return False
    except Exception as e:
        print(f"    ✗ エラー: {e}")
        return False


def main():
    apply = '--apply' in sys.argv
    do_predict = '--predict' in sys.argv

    # 期間（デフォルト：今日から7日後まで）
    date_from = date.today()
    date_to = date_from + timedelta(days=7)
    if '--date' in sys.argv:
        idx = sys.argv.index('--date')
        if idx + 1 < len(sys.argv):
            date_from = datetime.strptime(sys.argv[idx + 1], '%Y-%m-%d').date()
            date_to = date_from + timedelta(days=1)

    print("=" * 60)
    print(f"  レース名整合性チェック ({date_from} 〜 {date_to})")
    mode = '実行' if apply else 'ドライラン（検出のみ）'
    predict_mode = ' + 未予想を予想実行' if do_predict else ''
    print(f"  モード: {mode}{predict_mode}")
    print("=" * 60)

    conn = get_conn()
    try:
        mismatches = find_mismatches(conn, date_from, date_to)

        if not mismatches:
            print("  対象レースがありません")
            return

        ok_count = 0
        fixed_count = 0
        predicted_count = 0
        skipped_count = 0

        for race_date, entry_name, status, matched, horses in mismatches:
            line = f"  {race_date} {entry_name:<25}"
            if status == 'OK':
                print(f"{line} ✅ ({horses}頭)")
                ok_count += 1
            elif status == 'NO_HORSES':
                print(f"{line} ⚠️  出走馬データなし")
                ok_count += 1
            elif status == 'MISMATCH':
                print(f"{line} 🔧 名前不一致 → '{matched}' ({horses}頭)")
                if apply:
                    fix_mismatch(conn, entry_name, matched)
                    print(f"       ✓ '{matched}' → '{entry_name}' にリネーム")
                    fixed_count += 1
            elif status == 'NOT_PREDICTED':
                print(f"{line} ❌ 未予想")
                if apply and do_predict:
                    if run_prediction(entry_name):
                        predicted_count += 1
                    else:
                        skipped_count += 1
                else:
                    skipped_count += 1

        print("=" * 60)
        print(f"  ✅ 表示OK     : {ok_count}件")
        print(f"  🔧 名前修正   : {fixed_count}件")
        print(f"  ▶️  新規予想   : {predicted_count}件")
        print(f"  ⏭️  スキップ   : {skipped_count}件")
        print("=" * 60)
    finally:
        conn.close()

    if not apply and (fixed_count + skipped_count > 0 or any(m[2] in ('MISMATCH', 'NOT_PREDICTED') for m in mismatches)):
        print("\n  💡 自動修正するには --apply オプションを付けて再実行してください")
        print("  💡 未予想も予想する場合は --apply --predict")


if __name__ == '__main__':
    main()
