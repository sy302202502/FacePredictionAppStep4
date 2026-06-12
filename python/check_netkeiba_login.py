"""netkeibaプレミアムログインの診断スクリプト（認証情報は表示しない）"""
import os, re, requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

uid = os.getenv('NETKEIBA_LOGIN_ID', '')
pw  = os.getenv('NETKEIBA_PASSWORD', '')

print(f"LOGIN_ID : 長さ{len(uid)} / @含む={'@' in uid} / 先頭2文字={uid[:2]}*** / 空白含む={' ' in uid}")
print(f"PASSWORD : 長さ{len(pw)} / 空白含む={' ' in pw} / 引用符含む={any(c in pw for c in chr(34) + chr(39))}")

if not uid or not pw:
    print("❌ 認証情報が読み込めていません")
    raise SystemExit(1)

URL = 'https://race.netkeiba.com/race/oikiri.html?race_id=202602010111'

s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'})

# 本番と同じ順序: ページ取得（基本Cookie確立）→ ログイン → 再取得
r0 = s.get(URL, timeout=15)
print(f"事前GET: {r0.status_code} / cookies: {sorted(c.name for c in s.cookies)}")

r = s.post('https://regist.netkeiba.com/account/', data={
    'pid': 'login', 'action': 'auth', 'return_url2': '', 'mem_tp': '',
    'login_id': uid, 'pswd': pw,
}, timeout=15)
print(f"ログインPOST: {r.status_code}")
print(f"nkauth cookie: {any(c.name == 'nkauth' for c in s.cookies)}")
if 'パスワード' in r.text and '違' in r.text:
    print("⚠️ パスワード不一致の文言を検出")

r2 = s.get(URL, timeout=15)
r2.encoding = 'EUC-JP'
from stats_predictor import _parse_oikiri_page
data = _parse_oikiri_page(r2.text)
times = sum(1 for v in data.values() if v['has_time'])
print(f"取得: {len(data)}頭 / タイム付き: {times}頭")
print("✅ プレミアム取得OK" if times > 0 else "❌ タイム取得不可（ログイン失敗 or 権限なし）")
