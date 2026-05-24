"""
llm_client.py
LLM呼び出し抽象化レイヤー

対応プロバイダー（LLM_PROVIDER 環境変数で切り替え）:
  ollama   : ローカル Ollama (デフォルト・後方互換)
  groq     : Groq API  (llama-3.2-vision / llava-v1.5)
  gemini   : Google Gemini API
  openrouter: OpenRouter (各種モデル)

必要な環境変数:
  LLM_PROVIDER        = ollama | groq | gemini | openrouter
  OLLAMA_URL          = http://localhost:11434  (ollama のみ)
  OLLAMA_MODEL        = llava:7b               (ollama のみ)
  GROQ_API_KEY        = gsk_...                (groq のみ)
  GROQ_MODEL          = meta-llama/llama-4-scout-17b-16e-instruct (groq のみ)
  GEMINI_API_KEY      = AIza...                (gemini のみ)
  GEMINI_MODEL        = gemini-2.0-flash       (gemini のみ)
  OPENROUTER_API_KEY  = sk-or-...              (openrouter のみ)
  OPENROUTER_MODEL    = meta-llama/llama-3.2-11b-vision-instruct (openrouter のみ)
"""

import os
import json
import time
import base64
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=False)

# ──────────────────────────────────────────────
# 設定読み込み
# ──────────────────────────────────────────────
PROVIDER       = os.environ.get('LLM_PROVIDER', 'ollama').lower()
OLLAMA_BASE    = os.environ.get('OLLAMA_URL',  'http://localhost:11434')
OLLAMA_MODEL   = os.environ.get('OLLAMA_MODEL', 'llava:7b')
GROQ_API_KEY   = os.environ.get('GROQ_API_KEY', '')
GROQ_MODEL     = os.environ.get('GROQ_MODEL',  'meta-llama/llama-4-scout-17b-16e-instruct')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL   = os.environ.get('GEMINI_MODEL', 'gemini-2.0-flash')
OR_API_KEY     = os.environ.get('OPENROUTER_API_KEY', '')
OR_MODEL       = os.environ.get('OPENROUTER_MODEL', 'meta-llama/llama-3.2-11b-vision-instruct')

TIMEOUT_CONNECT = 15
TIMEOUT_READ    = 300  # クラウドAPIは高速なのでOllamaより短くてよい

# ──────────────────────────────────────────────
# プロバイダー別実装
# ──────────────────────────────────────────────

def _call_ollama(image_b64: str, prompt: str) -> str | None:
    """Ollama /api/generate (ストリーミング)"""
    url = f"{OLLAMA_BASE}/api/generate"
    try:
        resp = requests.post(url, json={
            'model': OLLAMA_MODEL,
            'prompt': prompt,
            'images': [image_b64],
            'stream': True,
            'keep_alive': 1800,
            'options': {'temperature': 0.5}
        }, stream=True, timeout=(TIMEOUT_CONNECT, 600))
        resp.raise_for_status()
        raw = ''
        for line in resp.iter_lines():
            if line:
                try:
                    chunk = json.loads(line.decode())
                    raw += chunk.get('response', '')
                    if chunk.get('done', False):
                        break
                except json.JSONDecodeError:
                    pass
        return raw
    except requests.exceptions.ConnectionError:
        print("    [エラー] Ollamaに接続できません。ollama serve が起動しているか確認してください")
        return None
    except requests.exceptions.Timeout:
        print("    [エラー] llava応答タイムアウト。スキップして次の馬へ")
        return None
    except Exception as e:
        print(f"    [llm エラー] Ollama: {e}")
        return None


def _call_groq(image_b64: str, prompt: str, mime: str = 'image/jpeg') -> str | None:
    """Groq Vision API (OpenAI互換) — 429レート制限時に最大3回リトライ"""
    if not GROQ_API_KEY:
        print("    [エラー] GROQ_API_KEY が未設定です")
        return None
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": GROQ_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                {"type": "text", "text": prompt}
            ]
        }],
        "temperature": 0.5,
        "max_tokens": 1024
    }
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload,
                                 headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                                 timeout=(TIMEOUT_CONNECT, TIMEOUT_READ))
            if resp.status_code == 429:
                wait = float(resp.headers.get('retry-after', 60))
                if wait > 30:
                    # 長時間待機が必要な場合は即時Noneを返してフォールバックさせる
                    print(f"    [レート制限] Groq 429: retry-after={wait:.0f}秒 → フォールバックへ")
                    return None
                print(f"    [レート制限] Groq 429: {wait:.0f}秒待機してリトライ ({attempt+1}/3)...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()['choices'][0]['message']['content']
        except requests.exceptions.Timeout:
            wait = 2 ** attempt
            print(f"    [タイムアウト] Groq: {wait}秒後リトライ ({attempt+1}/3)")
            if attempt < 2:
                time.sleep(wait)
        except Exception as e:
            print(f"    [llm エラー] Groq: {e}")
            return None
    return None


def _call_gemini(image_b64: str, prompt: str, mime: str = 'image/jpeg') -> str | None:
    """Google Gemini Vision API (REST) — 429時に最大3回リトライ"""
    if not GEMINI_API_KEY:
        print("    [エラー] GEMINI_API_KEY が未設定です")
        return None
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")
    payload = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": mime, "data": image_b64}},
            {"text": prompt}
        ]}],
        "generationConfig": {"temperature": 0.5, "maxOutputTokens": 1024}
    }
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload,
                                 timeout=(TIMEOUT_CONNECT, TIMEOUT_READ))
            if resp.status_code == 429:
                wait = float(resp.headers.get('retry-after', 2 ** (attempt + 1)))
                print(f"    [レート制限] Gemini 429: {wait:.0f}秒待機してリトライ ({attempt+1}/3)...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            candidates = resp.json().get('candidates', [])
            if not candidates:
                return None
            return candidates[0]['content']['parts'][0]['text']
        except Exception as e:
            print(f"    [llm エラー] Gemini: {e}")
            return None
    return None


def _call_openrouter(image_b64: str, prompt: str, mime: str = 'image/jpeg') -> str | None:
    """OpenRouter (OpenAI互換)"""
    if not OR_API_KEY:
        print("    [エラー] OPENROUTER_API_KEY が未設定です")
        return None
    url = "https://openrouter.ai/api/v1/chat/completions"
    payload = {
        "model": OR_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                {"type": "text", "text": prompt}
            ]
        }],
        "temperature": 0.5,
        "max_tokens": 1024
    }
    headers = {
        "Authorization": f"Bearer {OR_API_KEY}",
        "HTTP-Referer": "https://github.com/faceprediction"
    }
    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers,
                                 timeout=(TIMEOUT_CONNECT, TIMEOUT_READ))
            if resp.status_code == 429:
                wait = float(resp.headers.get('retry-after', 2 ** (attempt + 1)))
                print(f"    [llm] OpenRouter レート制限 — {wait:.0f}秒待機")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()['choices'][0]['message']['content']
        except Exception as e:
            print(f"    [llm エラー] OpenRouter attempt={attempt+1}: {e}")
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
    return None


# ──────────────────────────────────────────────
# 公開インターフェース
# ──────────────────────────────────────────────

# フォールバック順序: 設定プロバイダー → groq → gemini → openrouter → ollama
_FALLBACK_ORDER = ['groq', 'gemini', 'openrouter', 'ollama']

def _call_provider(provider: str, image_b64: str, prompt: str, mime: str) -> str | None:
    if provider == 'groq':
        return _call_groq(image_b64, prompt, mime)
    elif provider == 'gemini':
        return _call_gemini(image_b64, prompt, mime)
    elif provider == 'openrouter':
        return _call_openrouter(image_b64, prompt, mime)
    else:
        return _call_ollama(image_b64, prompt)

def _has_key(provider: str) -> bool:
    return {
        'groq': bool(GROQ_API_KEY),
        'gemini': bool(GEMINI_API_KEY),
        'openrouter': bool(OR_API_KEY),
        'ollama': True,
    }.get(provider, False)


def analyze_image(image_path: str, prompt: str) -> str | None:
    """
    画像ファイルを読み込み、LLMで分析してテキストを返す。
    設定プロバイダーが429/失敗した場合、自動的に次のプロバイダーへフォールバック。

    戻り値: LLMの生テキスト or None (全プロバイダー失敗時)
    """
    if not os.path.exists(image_path):
        return None

    ext = os.path.splitext(image_path)[1].lower()
    mime = 'image/png' if ext == '.png' else 'image/jpeg'

    with open(image_path, 'rb') as f:
        image_b64 = base64.b64encode(f.read()).decode()

    # 設定プロバイダーを先頭に、残りをフォールバック順で試行
    order = [PROVIDER] + [p for p in _FALLBACK_ORDER if p != PROVIDER]
    for provider in order:
        if not _has_key(provider):
            continue
        print(f"    [LLM] {provider} で分析中...", end=' ', flush=True)
        result = _call_provider(provider, image_b64, prompt, mime)
        if result:
            if provider != PROVIDER:
                print(f"→ {provider} にフォールバック成功")
            return result
        print(f"→ 失敗、次のプロバイダーへ")

    return None


def current_provider() -> str:
    """現在のプロバイダー名を返す（ログ表示用）"""
    model = {
        'groq': GROQ_MODEL,
        'gemini': GEMINI_MODEL,
        'openrouter': OR_MODEL,
        'ollama': OLLAMA_MODEL,
    }.get(PROVIDER, OLLAMA_MODEL)
    return f"{PROVIDER}:{model} (fallback有効)"
