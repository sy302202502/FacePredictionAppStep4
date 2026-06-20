"""verify_names.py — 出馬表の馬名が文字化けせず取得できるか確認する
使い方: python verify_names.py 202609030411
"""
import sys
from entry_fetcher import fetch_shutuba_entries
from constants import is_garbled

race_id = sys.argv[1] if len(sys.argv) > 1 else '202609030411'
entries, distance, surface, race_name, venue = fetch_shutuba_entries(race_id)

print(f"race_id={race_id}  取得 {len(entries)}頭")
if not entries:
    print("⚠️ 0頭（文字化けガードで保存中止 or 出馬表未確定の可能性）")
else:
    bad = 0
    for e in entries:
        mark = '❌化け' if is_garbled(e['horse_name']) else '✅'
        if is_garbled(e['horse_name']):
            bad += 1
        print(f"  {e.get('horse_number')}番 {e['horse_name']} {mark}")
    print(f"\n判定: {'❌ 文字化けあり' if bad else '✅ 全頭正常'}")
