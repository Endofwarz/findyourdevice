# backend/reddit_live.py
import os, time, requests

REDDIT_TOKEN = None
REDDIT_TOKEN_EXP = 0

def _env_summary():
    # redact values, only show presence/length
    def present(k):
        v = os.getenv(k)
        return dict(set=bool(v), length=len(v or ""))  # no secrets leaked
    return {
        "REDDIT_CLIENT_ID": present("REDDIT_CLIENT_ID"),
        "REDDIT_SECRET": present("REDDIT_SECRET"),
        "REDDIT_USERNAME": present("REDDIT_USERNAME"),
        "REDDIT_PASSWORD": present("REDDIT_PASSWORD"),
        "REDDIT_USER_AGENT": present("REDDIT_USER_AGENT"),
        "USE_REDDIT_LIVE": {"set": os.getenv("USE_REDDIT_LIVE") == "1", "value": os.getenv("USE_REDDIT_LIVE")},
    }

def _reddit_token(debug=False):
    """
    Password grant for Script apps (recommended for server-to-server).
    Falls back to cached token until expiry.
    Raises a RuntimeError with details on failure.
    """
    global REDDIT_TOKEN, REDDIT_TOKEN_EXP
    if time.time() < REDDIT_TOKEN_EXP - 30 and REDDIT_TOKEN:
        return REDDIT_TOKEN

    cid = os.getenv("REDDIT_CLIENT_ID")
    sec = os.getenv("REDDIT_SECRET")
    user = os.getenv("REDDIT_USERNAME")
    pwd  = os.getenv("REDDIT_PASSWORD")
    ua   = os.getenv("REDDIT_USER_AGENT", "findyourdevice/1.0")

    missing = [k for k,v in dict(REDDIT_CLIENT_ID=cid,REDDIT_SECRET=sec,REDDIT_USERNAME=user,REDDIT_PASSWORD=pwd).items() if not v]
    if missing:
        raise RuntimeError(f"Missing Reddit env vars: {', '.join(missing)}")

    try:
        r = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type": "password", "username": user, "password": pwd},
            auth=(cid, sec),
            headers={"User-Agent": ua},
            timeout=20,
        )
    except Exception as e:
        raise RuntimeError(f"Token request error: {e!r}")

    if r.status_code != 200:
        # include short excerpt of body for clarity
        body = (r.text or "")[:400]
        raise RuntimeError(f"Token request failed: {r.status_code} {r.reason}; body={body!r}")

    js = r.json()
    token = js.get("access_token")
    if not token:
        raise RuntimeError(f"Token missing in response: {js}")

    REDDIT_TOKEN = token
    REDDIT_TOKEN_EXP = time.time() + int(js.get("expires_in", 3600))
    return token

def reddit_search_raw(query: str, limit: int = 4):
    """Return (status_code, body_text, json_or_none). Uses oauth.reddit.com."""
    ua = os.getenv("REDDIT_USER_AGENT", "findyourdevice/1.0")
    token = _reddit_token()
    try:
        r = requests.get(
            "https://oauth.reddit.com/search",
            headers={"Authorization": f"bearer {token}", "User-Agent": ua},
            params={"q": query, "sort": "relevance", "t": "year", "type": "link", "limit": str(limit)},
            timeout=25,
        )
        body = r.text or ""
        js = None
        try:
            js = r.json()
        except Exception:
            js = None
        return r.status_code, body[:800], js
    except Exception as e:
        raise RuntimeError(f"Search request error: {e!r}")

def reddit_search_pros_cons(brand: str, model: str, limit: int = 4):
    """Very light heuristic; returns (pros, cons)."""
    if os.getenv("USE_REDDIT_LIVE", "0") != "1":
        return [], []
    q = f"\"{brand} {model}\" review OR battery OR camera OR heating OR lag OR bug"
    status, body, js = reddit_search_raw(q, limit=limit)
    if status != 200 or not js:
        raise RuntimeError(f"Reddit search failed: status={status}; body_excerpt={body[:240]!r}")
    pros, cons = [], []
    for child in (js.get("data", {}).get("children") or []):
        t = (child.get("data", {}).get("title") or "") + " " + (child.get("data", {}).get("selftext") or "")
        tl = t.lower()
        if any(x in tl for x in ["great camera", "amazing camera", "excellent battery", "solid battery", "snappy", "love the screen"]):
            pros.append("Praised by Reddit users")
        if any(x in tl for x in ["overheat", "overheats", "battery drain", "laggy", "throttle", "scratches"]):
            cons.append("Reported issues by Reddit users")
    return pros[:3], cons[:3]

def reddit_diag(brand: str = "Apple", model: str = "16 Pro Max"):
    """
    Return a verbose diagnostic JSON so we can see *exactly* where it fails.
    """
    out = {
        "env": _env_summary(),
        "token_ok": False,
        "token_error": None,
        "search_ok": False,
        "search_status": None,
        "search_excerpt": None,
        "search_error": None,
        "pros_cons_ok": False,
        "pros": [],
        "cons": [],
        "pros_cons_error": None,
    }

    try:
        token = _reddit_token()
        out["token_ok"] = True
        out["token_len"] = len(token)
    except Exception as e:
        out["token_error"] = str(e)
        return out  # can't continue

    try:
        q = f"\"{brand} {model}\" review OR battery OR camera OR heating OR lag OR bug"
        status, body, js = reddit_search_raw(q, limit=2)
        out["search_status"] = status
        out["search_excerpt"] = (body or "")[:300]
        out["search_ok"] = (status == 200)
        if status != 200:
            return out
    except Exception as e:
        out["search_error"] = str(e)
        return out

    try:
        pros, cons = reddit_search_pros_cons(brand, model, limit=4)
        out["pros"], out["cons"] = pros, cons
        out["pros_cons_ok"] = True
    except Exception as e:
        out["pros_cons_error"] = str(e)

    return out
