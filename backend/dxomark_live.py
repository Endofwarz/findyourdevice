# backend/dxomark_live.py
import os, re, requests
from bs4 import BeautifulSoup

BASE = "https://www.dxomark.com/smartphones/"
HEADERS = {
    "User-Agent": os.getenv("DXO_UA", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.8",
}

def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[\s\-_/]+", " ", s)
    return s

def fetch_dxomark_camera_rank(brand: str, model: str) -> int | None:
    if os.getenv("USE_DXOMARK_LIVE", "0") != "1":
        return None
    try:
        r = requests.get(BASE, headers=HEADERS, timeout=18)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
    except Exception:
        # fall back to html.parser if lxml not present
        soup = BeautifulSoup(r.text, "html.parser")

    want = _norm(f"{brand} {model}")
    # cards often have links with the exact phone name; collect in order
    items = []
    for a in soup.select("a[href*='/smartphones/']"):
        name = (a.get_text(" ", strip=True) or "").strip()
        if not name: 
            continue
        # heuristic: only keep names that look like phone names (contain brand + some letters)
        if len(name) < 6: 
            continue
        items.append(name)

    # de-dup while preserving order
    seen = set()
    ordered = []
    for name in items:
        key = _norm(name)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(name)

    target = None
    target_idx = None
    for i, name in enumerate(ordered, start=1):
        if _norm(name).find(_norm(brand)) >= 0 and _norm(name).find(_norm(model)) >= 0:
            target = name
            target_idx = i
            break

    return int(target_idx) if target_idx else None
