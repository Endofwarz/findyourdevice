# backend/reddit_live.py
from __future__ import annotations
import os, time, requests, re
from typing import Tuple, List

_R_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID") or ""
_R_SECRET    = os.getenv("REDDIT_SECRET") or ""
_UA          = os.getenv("REDDIT_UA", "findyourdevice/1.0 (by u/yourusername)")
_USE_REDDIT   = os.getenv("USE_REDDIT_LIVE", "0") == "1"

_TOKEN: dict | None = None  # {"access_token": "...", "exp": 1234567890}

def _token() -> str | None:
    """Fetch or reuse app-only bearer token."""
    if not (_R_CLIENT_ID and _R_SECRET and _USE_REDDIT):
        return None
    global _TOKEN
    now = time.time()
    if _TOKEN and now < _TOKEN.get("exp", 0) - 30:
        return _TOKEN["access_token"]
    try:
        r = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=( _R_CLIENT_ID, _R_SECRET ),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": _UA},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        _TOKEN = {
            "access_token": data["access_token"],
            "exp": now + int(data.get("expires_in", 3600)),
        }
        return _TOKEN["access_token"]
    except Exception as e:
        print("[reddit] token fail:", e)
        return None

_KEYWORDS = [
    "review", "battery", "camera", "heating", "overheat", "lag", "bug", "issue",
    "screen", "display", "signal", "update", "throttling"
]

def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:160]

def reddit_signals_for_phone(brand: str, model: str) -> Tuple[List[str], List[str]]:
    """
    Returns (pros, cons) bullets. Safe to call without creds (returns [], []).
    """
    tok = _token()
    if not tok:
        return [], []

    q_name = f"\"{brand} {model}\" " + " OR ".join(_KEYWORDS)
    params = {
        "q": q_name,
        "sort": "relevance",
        "t": "year",
        "type": "link",
        "limit": "8",
        "restrict_sr": "false",
        "include_over_18": "on",
    }
    try:
        r = requests.get(
            "https://oauth.reddit.com/search",
            headers={"Authorization": f"bearer {tok}", "User-Agent": _UA},
            params=params,
            timeout=15,
        )
        r.raise_for_status()
        js = r.json()
        items = js.get("data", {}).get("children", [])
        titles = [_clean(it.get("data", {}).get("title", "")) for it in items]
        titles = [t for t in titles if t]

        pros, cons = [], []
        for t in titles:
            lt = t.lower()
            if any(k in lt for k in ["battery life", "great camera", "love", "no issues", "smooth", "fast", "signal is good"]):
                pros.append(t)
            if any(k in lt for k in ["overheat", "heating", "lags", "bug", "issue", "scratch", "weak signal", "poor battery"]):
                cons.append(t)

        # cap + dedupe
        def _dedupe_cap(lst, cap):
            out, seen = [], set()
            for x in lst:
                k = x.lower()
                if k not in seen:
                    seen.add(k)
                    out.append(x)
                if len(out) >= cap:
                    break
            return out
        return _dedupe_cap(pros, 3), _dedupe_cap(cons, 3)
    except Exception as e:
        print("[reddit] failed:", e)
        return [], []
