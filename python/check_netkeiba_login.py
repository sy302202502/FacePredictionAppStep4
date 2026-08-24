"""netkeibaプレミアムログイン／接続の診断（認証情報は表示しない）

  docker compose exec -T python python3 python/check_netkeiba_login.py [race_id]

本番(stats_predictor)と同じ HEADERS を使う。ログイン試行は1回だけ
（アカウントロック回避のため繰り返さない）。
"""
import os, sys, re, requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)
from constants import HEADERS          # ← 本番と同じUAを使う
from stats_predictor import _parse_oikiri_page, _login_form, _netkeiba_login

RACE_ID = sys.argv[1] if len(sys.argv) > 1 else '202602011010'
URL = f'https://race.netkeiba.com/race/oikiri.html?race_id={RACE_ID}'

uid = os.getenv('NETKEIBA_LOGIN_ID', '')
pw  = os.getenv('NETKEIBA_PASSWORD', '')
print(f"LOGIN_ID : 長さ{len(uid)} / @含む={'@' in uid} / 先頭2文字={uid[:2]}***")
print(f"PASSWORD : 長さ{len(pw)} / 空白含む={' ' in pw}")
if not uid or not pw:
    print("❌ 認証情報が読み込めていません"); raise SystemExit(1)

print(f"\n対象: {URL}")
s = requests.Session()
s.headers.update(HEADERS)

# ── 1. 素の到達性（サイト全体が弾かれていないか）──
for name, u in [('トップ', 'https://race.netkeiba.com/'),
                ('追い切り', URL)]:
    try:
        r = s.get(u, timeout=20)
        body = r.content[:200].decode('euc-jp', 'ignore')
        print(f"[GET] {name:<5} HTTP {r.status_code} / {len(r.content)}bytes "
              f"/ cookies={sorted(c.name for c in s.cookies)}")
        if r.status_code != 200:
            print(f"       先頭200B: {body!r}")
    except Exception as e:
        print(f"[GET] {name:<5} 例外: {e}")

# ── 2. 未ログインでのパース（ランクが取れるか）──
try:
    r = s.get(URL, timeout=20)
    r.encoding = 'EUC-JP'
    d0 = _parse_oikiri_page(r.text)
    print(f"\n[未ログイン] {len(d0)}頭 / ランク有 "
          f"{sum(1 for v in d0.values() if v['rank'])}頭 / タイム有 "
          f"{sum(1 for v in d0.values() if v['has_time'])}頭")
except Exception as e:
    print(f"\n[未ログイン] 例外: {e}")
    d0 = {}

# ── 3. ログイン（1回だけ）──
# 本番と同じ経路を使う。フォームの送信先とhidden値はHTMLから毎回読む方式。
print("\n[ログイン試行] ※1回のみ")
action, payload = _login_form(s)
if action:
    print(f"  フォーム送信先: {action}")
    print(f"  フィールド    : {sorted(payload.keys())}")
else:
    print("  ⚠ ログインフォームを解析できません（サイト構造の変更を疑う）")
ok = _netkeiba_login(s)
print(f"  cookies: {sorted(c.name for c in s.cookies)}")
print(f"  nkauth : {ok}")

# ── 4. ログイン後のパース ──
r2 = s.get(URL, timeout=20); r2.encoding = 'EUC-JP'
d1 = _parse_oikiri_page(r2.text)
times = sum(1 for v in d1.values() if v['has_time'])
print(f"\n[ログイン後] {len(d1)}頭 / タイム有 {times}頭")
print("✅ プレミアム取得OK" if times > 0 else "❌ タイム取得不可")
