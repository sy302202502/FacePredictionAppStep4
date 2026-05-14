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
import base64
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'), override=True)

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
    """Groq Vision API (OpenAI互換)"""
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
    try:
        resp = requests.post(url, json=payload,
                             headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                             timeout=(TIMEOUT_CONNECT, TIMEOUT_READ))
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"    [llm エラー] Groq: {e}")
        return None


def _call_gemini(image_b64: str, prompt: str, mime: str = 'image/jpeg') -> str | None:
    """Google Gemini Vision API (REST)"""
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
    try:
        resp = requests.post(url, json=payload,
                             timeout=(TIMEOUT_CONNECT, TIMEOUT_READ))
        resp.raise_for_status()
        candidates = resp.json().get('candidates', [])
        if not candidates:
            return None
        return candidates[0]['content']['parts'][0]['text']
    except Exception as e:
        print(f"    [llm エラー] Gemini: {e}")
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
    try:
        resp = requests.post(url, json=payload,
                             headers={
                                 "Authorization": f"Bearer {OR_API_KEY}",
                                 "HTTP-Referer": "https://github.com/faceprediction"
                             },
                             timeout=(TIMEOUT_CONNECT, TIMEOUT_READ))
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"    [llm エラー] OpenRouter: {e}")
        return None


# ──────────────────────────────────────────────
# 公開インターフェース
# ──────────────────────────────────────────────

def analyze_image(image_path: str, prompt: str) -> str | None:
    """
    画像ファイルを読み込み、LLMで分析してテキストを返す。
    プロバイダーは LLM_PROVIDER 環境変数で切り替え。

    戻り値: LLMの生テキスト or None (失敗時)
    """
    if not os.path.exists(image_path):
        return None

    # MIME推定
    ext = os.path.splitext(image_path)[1].lower()
    mime = 'image/png' if ext == '.png' else 'image/jpeg'

    with open(image_path, 'rb') as f:
        image_b64 = base64.b64encode(f.read()).decode()

    if PROVIDER == 'groq':
        return _call_groq(image_b64, prompt, mime)
    elif PROVIDER == 'gemini':
        return _call_gemini(image_b64, prompt, mime)
    elif PROVIDER == 'openrouter':
        return _call_openrouter(image_b64, prompt, mime)
    else:  # ollama (default)
        return _call_ollama(image_b64, prompt)


def current_provider() -> str:
    """現在のプロバイダー名を返す（ログ表示用）"""
    model = {
        'groq': GROQ_MODEL,
        'gemini': GEMINI_MODEL,
        'openrouter': OR_MODEL,
        'ollama': OLLAMA_MODEL,
    }.get(PROVIDER, OLLAMA_MODEL)
    return f"{PROVIDER}:{model}"
