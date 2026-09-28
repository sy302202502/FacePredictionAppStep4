"""
repair_course.py — race_entry の芝/ダート・距離の誤データを出馬表から修復する

【背景】
  entry_fetcher は「ダート1700m」表記しか想定しておらず、netkeiba の実表記
  「ダ1700m」を読めなかった。そのためダート戦・障害戦がすべて
  surface='芝' / distance=NULL で保存され、統計予想は「芝2000m」として採点していた。

【処理】
  distance が NULL のレース（＝読めなかったレース）について出馬表の
  コース表記を取り直し、race_entry の surface / distance / race_category を更新する。
  --rescore を付けると、開催が今日以降のレースは統計予想を
  stats_predictor.py <race_id> --update で再計算する（顔面分析データは保持される）。

使い方:
  python3 python/repair_course.py                      # ドライラン（変更内容の表示のみ）
  python3 python/repair_course.py --apply              # race_entry を修復
  python3 python/repair_course.py --apply --rescore    # 修復＋今後のレースを再予想
  （VPS: docker compose exec python python3 python/repair_course.py --apply --rescore）
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

from bs4 import BeautifulSoup

from constants import fetch_with_retry, decode_netkeiba, parse_course
from entry_fetcher import get_conn, classify_race

JST = timezone(timedelta(hours=9))


def fetch_course(race_id):
    """出馬表のコース表記 → (surface, distance)。取れなければ (None, None)。"""
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    resp = fetch_with_retry(url, timeout=15, min_sleep=1.0, max_sleep=2.0)
    soup = BeautifulSoup(decode_netkeiba(resp), 'lxml')
    race_data = soup.find('div', class_='RaceData01')
    return parse_course(race_data.get_text() if race_data else '')


def main():
    apply = '--apply' in sys.argv
    rescore = '--rescore' in sys.argv
    today = datetime.now(JST).date()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT race_id, MIN(race_name), MIN(race_date), MIN(surface)
        FROM race_entry
        WHERE distance IS NULL AND race_id IS NOT NULL
        GROUP BY race_id
        ORDER BY MIN(race_date) DESC
    """)
    targets = cur.fetchall()
    conn.rollback()  # ネットワーク取得中にトランザクションを開いたままにしない
    print(f"距離不明のレース: {len(targets)}件{'（ドライラン）' if not apply else ''}\n")

    fixed, upcoming, failures = 0, [], []
    for race_id, race_name, race_date, old_surface in targets:
        try:
            surface, distance = fetch_course(race_id)
        except Exception as e:
            print(f"  ❌ {race_date} {race_name} ({race_id}) 取得失敗: {e}")
            failures.append(race_name)
            continue
        if not surface:
            print(f"  ⚠️ {race_date} {race_name} ({race_id}) コース表記を読めず")
            failures.append(race_name)
            continue
        category = classify_race(distance, surface)
        mark = '🔁' if surface != old_surface else '  '
        print(f"  {mark} {race_date} {race_name}: {old_surface}/不明 → {surface}{distance}m [{category}]")
        if apply:
            cur.execute("""
                UPDATE race_entry
                SET surface = %s, distance = %s, race_category = %s
                WHERE race_id = %s
            """, (surface, distance, category, race_id))
            conn.commit()
            fixed += 1
        if race_date and race_date >= today:
            upcoming.append((race_id, race_name))

    print(f"\n修復: {fixed}件 / 今日以降のレース: {len(upcoming)}件")

    if apply and rescore and upcoming:
        script = os.path.join(os.path.dirname(__file__), 'stats_predictor.py')
        for race_id, race_name in upcoming:
            print(f"\n=== 再予想: {race_name} ({race_id}) ===", flush=True)
            rc = subprocess.run([sys.executable, script, race_id, '--update'], timeout=1800).returncode
            print(f"  → {'OK' if rc == 0 else f'失敗 rc={rc}'}")
            if rc != 0:
                failures.append(f"{race_name}(再予想)")

    cur.close()
    conn.close()
    if failures:
        print(f"\n❌ 失敗 {len(failures)}件: {', '.join(failures)}（再実行してください）")
        sys.exit(1)


if __name__ == '__main__':
    main()
