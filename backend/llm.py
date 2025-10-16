# backend/llm.py
import os, json, time, hashlib, requests
from pathlib import Path
from typing import List, Dict, Any

import requests, os, time

GROQ_TIMEOUT = float(os.getenv("GROQ_TIMEOUT", "8"))   # seconds
GROQ_RETRIES = int(os.getenv("GROQ_RETRIES", "1"))

def _post_with_retry(url, json_payload, headers):
    last_err = None
    for attempt in range(GROQ_RETRIES + 1):
        try:
            return requests.post(url, json=json_payload, headers=headers, timeout=GROQ_TIMEOUT)
        except Exception as e:
            last_err = e
            if attempt < GROQ_RETRIES:
                time.sleep(0.5)
    raise last_err

# Compute our own paths (no config import needed)
BACKEND_DIR = Path(__file__).resolve().parent

# Read env directly (so we don't break if config.py changes)
def _as_bool(v, default=False):
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}

USE_LLM         = _as_bool(os.getenv("USE_LLM"), False)
GROQ_API_KEY    = os.getenv("GROQ_API_KEY")
LLM_BASE_URL    = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_MODEL_FINAL = os.getenv("LLM_MODEL_FINAL", "llama-3.3-70b-versatile")
LLM_MAX_TOKENS  = int(os.getenv("LLM_MAX_TOKENS", "350"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.6"))

# simple file cache dir
CACHE_DIR = BACKEND_DIR / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

def _hash_key(payload: Dict[str, Any]) -> str:
    s = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _cache_read(key: str):
    p = CACHE_DIR / f"{key}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except:
            return None
    return None

def _cache_write(key: str, value: Dict[str, Any]):
    p = CACHE_DIR / f"{key}.json"
    try:
        p.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    except:
        pass
# backend/llm.py

# --- minimal Groq implementation; returns text ---
def chat_complete(messages, *, model=None, max_tokens=256, temperature=0.6):
    import os, requests, json, time
    from hashlib import sha256

    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    MODEL = model or os.getenv("LLM_MODEL_FINAL", "llama-3.3-70b-versatile")


    # If key missing, return None (caller will fallback)
    if not GROQ_API_KEY:
        return None

    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

    # Simple retry (429/503)
    backoff = 1.0
    for _ in range(5):
        r = requests.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=30)
        if r.status_code == 200:
            data = r.json()
            return data["choices"][0]["message"]["content"]
        if r.status_code in (429, 503):
            retry_after = r.headers.get("retry-after")
            time.sleep(float(retry_after) if retry_after else backoff)
            backoff = min(backoff * 2, 10)
            continue
        break

    # If we got here, give up and let caller fallback
    return None