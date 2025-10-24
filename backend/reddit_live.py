# backend/reddit_live.py
from __future__ import annotations
import os, time, base64
from typing import Tuple, List
import requests

OAUTH = "https://oauth.reddit.com"
AUTH  = "https://www.reddit.com/api/v1/access_token"

CLIENT_ID     = os.getenv("REDDIT_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("REDDIT_SECRET", "").strip()
USER_AGENT    = os.getenv("REDDIT_USER_AGENT", "findyourdevice/0.1 by unknown").strip()

_token_cache = {"value": None, "exp": 0}

def _get_app_token() -> str:
    # cache token ~45 minutes
    now = time.time()
    if _token_cache["value"] and now < _token_cache["exp"] - 60:
        return _token_cache["value"]

    auth = requests.auth.HTTPBasicAuth(CLIENT_ID, CLIENT_SECRET)
    headers = {"User-Agent": USER_AGENT}
    data = {"grant_type": "client_credentials"}
    r = requests.post(AUTH, auth=auth, data=data, headers=headers, timeout=15)
    r.raise_for_status()
    tok = r.json().get("access_token")
    if not tok:
        raise RuntimeError("No reddit access_token in response")
    _token_cache["value"] = tok
    _token_cache["exp"] = now + 3600
    return tok

def _search_links(q: str, limit: int = 4) -> List[dict]:
    tok = _get_app_token()
    headers = {"Authorization": f"bearer {tok}", "User-Agent": USER_AGENT}
    params = {
        "q": q,
        "sort": "relevance",
        "t": "year",
        "type": "link",
        "limit": str(limit),
        "include_over_18": "on",
        "raw_json": "1",
        "restrict_sr": "false",
    }
    url = f"{OAUTH}/search"
    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    return (r.json() or {}).get("data", {}).get("children", [])

def reddit_signals_for_phone(slug: str, brand: str, model: str) -> Tuple[List[str], List[str]]:
    """
    Returns (pros, cons) lists pulled from recent reddit titles.
    Very light heuristics: look for +words / -words patterns in titles.
    """
    brand, model = (brand or "").strip(), (model or "").strip()
    if not brand or not model:
        return [], []

    q = f"\"{brand} {model}\" review OR battery OR camera OR heating OR heat OR lag OR bug"
    try:
        posts = _search_links(q, limit=6)
    except Exception as e:
        print("[reddit] search failed:", e)
        return [], []

    titles = [ (p.get("data") or {}).get("title") or "" for p in posts ]
    # ultra-simple heuristics
    good_kw = ("battery life", "great battery", "fast", "camera", "durable", "update", "stable", "no issues")
    bad_kw  = ("overheating", "heating", "hot", "lag", "bug", "issue", "problem", "throttle", "drain")

    pros, cons = [], []
    for t in titles:
        lo = t.lower()
        if any(k in lo for k in good_kw):
            pros.append(t)
        if any(k in lo for k in bad_kw):
            cons.append(t)

    # cap + de-dupe
    def uniq(lst, cap): 
        out, seen = [], set()
        for s in lst:
            s = s.strip()
            k = s.lower()
            if s and k not in seen:
                seen.add(k); out.append(s)
            if len(out) >= cap: break
        return out

    return uniq(pros, 3), uniq(cons, 3)
