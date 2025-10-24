# backend/reddit_live.py
import os, time, requests

REDDIT_TOKEN = None
REDDIT_TOKEN_EXP = 0

def _reddit_token():
    global REDDIT_TOKEN, REDDIT_TOKEN_EXP
    if time.time() < REDDIT_TOKEN_EXP - 30 and REDDIT_TOKEN:
        return REDDIT_TOKEN
    cid = os.getenv("REDDIT_CLIENT_ID")
    sec = os.getenv("REDDIT_SECRET")
    user = os.getenv("REDDIT_USERNAME")
    pwd = os.getenv("REDDIT_PASSWORD")
    ua  = os.getenv("REDDIT_USER_AGENT", "findyourdevice/1.0")

    if not all([cid, sec, user, pwd]):
        raise RuntimeError("Reddit creds missing (need CLIENT_ID, SECRET, USERNAME, PASSWORD)")

    r = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        data={"grant_type": "password", "username": user, "password": pwd},
        auth=(cid, sec),
        headers={"User-Agent": ua},
        timeout=15
    )
    r.raise_for_status()
    data = r.json()
    REDDIT_TOKEN = data["access_token"]
    REDDIT_TOKEN_EXP = time.time() + int(data.get("expires_in", 3600))
    return REDDIT_TOKEN

def reddit_search_pros_cons(brand: str, model: str, limit: int = 4):
    """Returns (pros, cons) lists from a few recent relevant posts."""
    if os.getenv("USE_REDDIT_LIVE", "0") != "1":
        return [], []
    ua = os.getenv("REDDIT_USER_AGENT", "findyourdevice/1.0")
    token = _reddit_token()
    q = f"\"{brand} {model}\" review OR battery OR camera OR heating OR lag OR bug"
    r = requests.get(
        "https://oauth.reddit.com/search",
        headers={"Authorization": f"bearer {token}", "User-Agent": ua},
        params={"q": q, "sort": "relevance", "t": "year", "type": "link", "limit": str(limit)},
        timeout=20
    )
    r.raise_for_status()
    js = r.json()
    pros, cons = [], []
    for child in (js.get("data", {}).get("children") or []):
        t = (child.get("data", {}).get("title") or "") + " " + (child.get("data", {}).get("selftext") or "")
        tl = t.lower()
        # very light heuristics: feel free to refine later
        if any(x in tl for x in ["great camera", "amazing battery", "no overheating", "snappy", "love the screen"]):
            pros.append("Praised by Reddit users")
        if any(x in tl for x in ["overheats", "battery drain", "laggy", "throttle", "scratches easily"]):
            cons.append("Reported issues by Reddit users")
    return pros[:3], cons[:3]
