# backend/ai_intent.py
import os, json
import requests

__all__ = ["safe_merge_ai_intent"]

def _ai_extract_intent(text: str) -> dict:
    """
    Use Ollama (format=json) to extract phone-shopping intent from free-form text.
    Returns {} on any error (so callers never break).
    """
    try:
        ollama_url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
        model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")

        schema = {
            "type": "object",
            "properties": {
                "budget": {"type": ["number", "null"]},
                "os": {"type": ["string", "null"]},
                "prefer_small": {"type": ["boolean", "null"]},
                "prefer_large": {"type": ["boolean", "null"]},
                "min_battery": {"type": ["integer", "null"]},
                "min_ram": {"type": ["number", "null"]},
                "min_storage": {"type": ["number", "null"]},
                "min_camera": {"type": ["number", "null"]},
                "brands": {"type": ["array", "null"], "items": {"type": "string"}},
                "avoid_brands": {"type": ["array", "null"], "items": {"type": "string"}},
                "must_have": {"type": ["array", "null"], "items": {"type": "string"}},
                "min_year": {"type": ["integer", "null"]},
                "max_year": {"type": ["integer", "null"]},
            },
            "additionalProperties": False,
        }

        sys = (
            "Extract phone-shopping intent from the user message. "
            "Return STRICT JSON only that matches this schema:\n"
            f"{json.dumps(schema)}\n\n"
            "Guidelines:\n"
            "- budget: numeric USD if present (e.g., 'under 800', '$500', 'max 700').\n"
            "- os: 'android' or 'ios' if clearly preferred; otherwise null.\n"
            "- prefer_small for compact (~6.1”), prefer_large for big (~6.7”+).\n"
            "- min_battery if they imply battery life (e.g., 'long battery' -> 5000).\n"
            "- min_ram, min_storage, min_camera if stated.\n"
            "- brands (liked) and avoid_brands (disliked).\n"
            "- must_have features like 5g, wireless charging, ip68, esim, telephoto, macro, sd card.\n"
            "- min_year / max_year if they say 'latest/new/from 2024'.\n"
            "If a field is missing, set it to null. Do not invent values."
        )

        payload = {
            "model": model,
            "prompt": sys + "\n\nUser message:\n" + text + "\n\nJSON:",
            "format": "json",
            "stream": False,
        }
        r = requests.post(f"{ollama_url}/api/generate", json=payload, timeout=20)
        r.raise_for_status()
        raw = r.json().get("response", "{}").strip()
        data = json.loads(raw)

        # normalize “both size prefs set” -> none
        if data.get("prefer_small") and data.get("prefer_large"):
            data["prefer_small"] = None
            data["prefer_large"] = None

        # dedupe arrays case-insensitively
        for k in ("brands", "avoid_brands", "must_have"):
            if data.get(k):
                seen = set(); out = []
                for s in data[k]:
                    s2 = (s or "").strip()
                    if s2 and s2.lower() not in seen:
                        seen.add(s2.lower()); out.append(s2)
                data[k] = out

        # drop null/empty
        return {k: v for k, v in data.items() if v not in (None, "", [], {})}
    except Exception:
        return {}

def safe_merge_ai_intent(user_text: str, current: dict) -> dict:
    """
    Call the extractor and merge fields into `current` ONLY where empty.
    Never raises; returns the updated dict.
    """
    try:
        delta = _ai_extract_intent(user_text)
        if isinstance(delta, dict):
            for k, v in delta.items():
                if v in (None, "", [], {}):
                    continue
                if current.get(k) in (None, "", [], {}):
                    current[k] = v
    except Exception:
        pass
    return current
