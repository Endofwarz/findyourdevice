# backend/dxomark_live.py
from __future__ import annotations
import os, re, time
from typing import Optional, Tuple
import requests
from bs4 import BeautifulSoup

DXO_BASE = "https://www.dxomark.com"
HEADERS = {
    "User-Agent": os.getenv("REDDIT_USER_AGENT") or "Mozilla/5.0 (compatible; DXOFetch/1.0)",
    "Accept-Language": "en-US,en;q=0.8",
}
# tiny in-memory cache (avoid rate limits)
_CACHE: dict[str, Tuple[float, Optional[int]]] = {}
_TTL = 60 * 60  # 1 hour

def _now() -> float:
    return time.time()

def _get(url: str, timeout: float = 12.0) -> str:
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.text

def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")

def _norm(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("’", "'")
    s = re.sub(r"[^a-z0-9+ ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # unifying common phone suffixes
    s = s.replace(" pro max", " pro max")
    s = s.replace(" pro+", " pro plus")
    s = s.replace(" plus", " plus")
    return s

def _name_key(brand: str, model: str) -> str:
    return f"{_norm(brand)}::{_norm(model)}"

def _matches(target: str, brand: str, model: str) -> bool:
    t = _norm(target)
    b = _norm(brand)
    m = _norm(model)
    # tolerate brand missing in the visible text (some tiles only show model)
    return (m in t and (b in t or True))

def _extract_rank_text(s: str) -> Optional[int]:
    # look for "#12", "No. 12", or "Rank 12"
    m = re.search(r"(?:#|no\.?\s*|rank\s*)(\d{1,3})", s, re.I)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None

def _search_smartphones_listing_for_rank(brand: str, model: str) -> Optional[int]:
    """
    Scrape https://www.dxomark.com/smartphones/ listing page and try to find
    a tile/card with the phone name and its displayed rank.
    """
    html = _get(f"{DXO_BASE}/smartphones/")
    soup = _soup(html)

    # 1) look for obvious badges with numbers (e.g., tiles/cards)
    candidates = []
    for node in soup.select("a, div, span"):
        txt = (node.get_text(" ", strip=True) or "")
        if not txt:
            continue
        if _matches(txt, brand, model):
            # Try reading rank from node or close vicinity
            rank = _extract_rank_text(txt)
            if rank is None:
                near = " ".join((node.find_parent() or node).get_text(" ", strip=True)[:300].split())
                rank = _extract_rank_text(near)
            if rank is not None:
                candidates.append(rank)

    if candidates:
        # pick the smallest visible rank (safest)
        return min(candidates)

    return None

def fetch_dxomark_camera_rank(brand: str, model: str) -> Optional[int]:
    """
    Public entry. Returns the **rank number** (1…N) for the phone on DXOMARK's
    smartphones ranking page. None if not found.
    """
    if os.getenv("USE_DXOMARK_LIVE", "0") != "1":
        return None

    key = _name_key(brand, model)
    if key in _CACHE:
        ts, val = _CACHE[key]
        if _now() - ts < _TTL:
            return val

    try:
        rank = _search_smartphones_listing_for_rank(brand, model)
    except Exception as e:
        print("[dxo] listing fetch failed:", e)
        rank = None

    _CACHE[key] = (_now(), rank)
    return rank

# ---------- small debug helpers (used by /dxo/diag) ----------
def diag_dxomark(brand: str, model: str) -> dict:
    out = {
        "brand": brand, "model": model,
        "env": {"USE_DXOMARK_LIVE": os.getenv("USE_DXOMARK_LIVE", "0")},
        "result": None,
        "notes": [],
    }
    if os.getenv("USE_DXOMARK_LIVE", "0") != "1":
        out["notes"].append("USE_DXOMARK_LIVE is not '1' → scraper disabled")
        return out
    try:
        html = _get(f"{DXO_BASE}/smartphones/")
        out["notes"].append(f"listing_ok: {bool(html)}")
        soup = _soup(html)
        out["notes"].append(f"dom_ok: {bool(soup)}")
        # quick peek
        sample = soup.get_text(" ", strip=True)[:600]
        out["notes"].append(f"text_sample: {sample[:180]}…")
        out["result"] = fetch_dxomark_camera_rank(brand, model)
    except Exception as e:
        out["notes"].append(f"error: {e}")
    return out
