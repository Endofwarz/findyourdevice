# backend/llm.py
import os, json, time, hashlib, requests
from pathlib import Path
from typing import List, Dict, Any

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

def chat_complete(prompt: str, context: str = None):
    """
    Fallback stub for Render deploys without Groq.
    Returns a basic mock response so API stays functional.
    """
    print("⚠️ chat_complete(): Mock mode – no real Groq call")
    return {
        "text": f"Mock reply for: {prompt[:80]}",
        "model": "mock",
        "tokens": len(prompt.split()),
        "timestamp": time.time(),
    }