"""共通定数・ユーティリティモジュール"""

import time
import random
import requests

# 全スクリプト共通のリクエストヘッダー
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )
}


def polite_sleep(min_sec=1.0, max_sec=2.5):
    """BAN対策: ランダムな待機時間を挿入する"""
    time.sleep(random.uniform(min_sec, max_sec))


def fetch_with_retry(url, headers=None, timeout=15, retries=3, min_sleep=1.0, max_sleep=2.5):
    """リトライ付きHTTP GETリクエスト。失敗時は指数バックオフで再試行する。"""
    if headers is None:
        headers = HEADERS
    last_exc = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            polite_sleep(min_sleep, max_sleep)
            return resp
        except Exception as e:
            last_exc = e
            if attempt < retries - 1:
                wait = random.uniform(3.0, 6.0) * (attempt + 1)
                print(f"  [リトライ {attempt + 1}/{retries}] {wait:.1f}秒後に再試行: {e}", flush=True)
                time.sleep(wait)
    raise last_exc
