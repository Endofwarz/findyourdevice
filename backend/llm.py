# backend/llm.py
import os, json, time, hashlib, requests
from pathlib import Path
from typing import List, Dict, Any
from config import (
    USE_LLM, GROQ_API_KEY, LLM_BASE_URL, LLM_MODEL_FINAL,
    LLM_MAX_TOKENS, LLM_TEMPERATURE, BACKEND_DIR
)

CACHE_DIR = BACKEND_DIR / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

def _hash_key(payload: Dict[str, Any]) -> str:
    s = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    import hashlib as _h
    return _h.sha256(s.encode("utf-8")).hexdigest()

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

def chat_complete(messages: List[Dict[str, str]], *, model: str = None,
                  max_tokens: int = None, temperature: float = None) -> str:
    """Call Groq /chat/completions; returns text. Uses simple cache + retry."""
    if not USE_LLM or not GROQ_API_KEY:
        raise RuntimeError("LLM disabled or missing GROQ_API_KEY")
    model = model or LLM_MODEL_FINAL
    max_tokens = max_tokens or LLM_MAX_TOKENS
    temperature = LLM_TEMPERATURE if temperature is None else temperature

    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    key = _hash_key(payload)
    cached = _cache_read(key)
    if cached: return cached["text"]

    url = f"{LLM_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

    backoff = 1.0
    for _ in range(5):
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        if r.status_code == 200:
            data = r.json()
            text = data["choices"][0]["message"]["content"]
            _cache_write(key, {"text": text})
            return text
        if r.status_code in (429, 503):
            retry_after = r.headers.get("retry-after")
            time.sleep(float(retry_after) if retry_after else backoff)
            backoff = min(backoff * 2, 10)
            continue
        raise RuntimeError(f"LLM error {r.status_code}: {r.text}")
    raise RuntimeError("LLM retry attempts exhausted")
