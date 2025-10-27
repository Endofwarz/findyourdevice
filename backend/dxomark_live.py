# backend/dxomark_live.py
from __future__ import annotations
import os, re, time
from typing import Optional
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

RANK_LIST_URLS = [
    # Primary: list sorted by Camera
    "https://www.dxomark.com/smartphones/?sort_by=camera",
    # Legacy path some regions still serve
    "https://www.dxomark.com/category/smartphones/",
    # “smartphone ranking” landing (sometimes server renders list)
    "https://www.dxomark.com/smartphones/smartphone-ranking/",
]

def _get(url: str, timeout: int = 12) -> str:
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.text

def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")

def _norm(s: str) -> str:
    s = re.sub(r"[\u00A0]+", " ", s or "")           # nbsp -> space
    s = re.sub(r"[^a-z0-9+ ]", " ", s.lower())       # keep + to preserve 'pro+'
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _canonical_name(brand: str, model: str) -> list[str]:
    """
    Build a few tolerant match keys (handles 'Pro Max' vs 'ProMax', etc.).
    """
    b = _norm(brand)
    m = _norm(model)

    # Common variants
    variants = set()
    base = f"{b} {m}".strip()
    variants.add(base)

    # 'pro max' <-> 'promax'
    variants.add(base.replace(" pro max", " promax"))
    variants.add(base.replace(" promax", " pro max"))

    # remove brand (DXO sometimes omits brand in internal anchors); keep model only as a weaker fallback
    variants.add(m)

    # plus/minus signs and spaces
    variants.add(base.replace(" +", "+"))
    variants.add(base.replace("+", " plus"))

    # remove storage/country tags just in case
    variants.add(re.sub(r"\b(5g|4g|dual sim|usa|china|eu|global)\b", "", base).strip())

    return [v for v in variants if v]

def _best_match_index(titles: list[str], keys: list[str]) -> Optional[int]:
    """
    Simple token containment/scoring: prefer full containment; fallback to highest token overlap.
    """
    norm_titles = [_norm(t) for t in titles]
    norm_keys   = [_norm(k) for k in keys]

    # 1) exact or full containment
    for ki, k in enumerate(norm_keys):
        for i, t in enumerate(norm_titles):
            if k and (k == t or k in t):
                return i

    # 2) token overlap
    best_i, best_score = None, 0
    for i, t in enumerate(norm_titles):
        tset = set(t.split())
        for k in norm_keys:
            kset = set(k.split())
            if not kset: 
                continue
            score = len(tset & kset) / max(1, len(kset))
            if score > best_score:
                best_score, best_i = score, i

    return best_i

def _parse_rank_from_list(html: str, brand: str, model: str) -> Optional[int]:
    soup = _soup(html)

    # Try several list shapes

    # A) Cards / rows with explicit “rank” cell/column
    rows = []
    # list items
    rows += soup.select("li,div.ranking-list-item,div.card,article")
    # table rows
    rows += soup.select("table tr")

    titles: list[str] = []
    for r in rows:
        txt = " ".join(x.get_text(" ", strip=True) for x in r.select("a, .title, .device, .card-title, .name") or [r])
        txt = re.sub(r"\s+", " ", txt).strip()
        if not txt:
            continue
        # Heuristic: keep only rows with smartphone-ish titles
        if any(w in txt.lower() for w in ["iphone", "galaxy", "pixel", "oneplus", "xiaomi", "vivo", "oppo", "honor", "huawei"]):
            titles.append(txt)

    if titles:
        idx = _best_match_index(titles, _canonical_name(brand, model))
        if idx is not None:
            # Rank is 1-based
            return idx + 1

    # B) Device page fallback — often contains “Overall ranking #N”
    # Try a few slug shapes
    guess_slugs = []
    nm = _norm(f"{brand} {model}")
    guess_slugs.append(re.sub(r"\s+", "-", nm))                       # apple-iphone-16-pro-max
    guess_slugs.append(re.sub(r"\s+", "-", _norm(model)))             # iphone-16-pro-max

    for g in guess_slugs:
        for suffix in ["-camera-review", "-camera-test", ""]:
            url = f"https://www.dxomark.com/smartphones/{g}{suffix}"
            try:
                page = _get(url)
            except Exception:
                continue
            m = re.search(r"(?:overall\s+ranking|global\s+ranking)\s*#?\s*(\d{1,3})", page, re.I)
            if not m:
                # sometimes they render “Ranking \n #7”
                m = re.search(r"ranking[^#]{0,15}#\s*(\d{1,3})", page, re.I)
            if m:
                return int(m.group(1))

    return None

def fetch_dxomark_camera_rank(brand: str, model: str) -> Optional[int]:
    """
    Returns 1-based DXOMARK camera rank for the given phone, or None.
    """
    if os.getenv("USE_DXOMARK_LIVE", "1") != "1":
        return None

    # Try main list pages first (fast + robust if server-rendered)
    for url in RANK_LIST_URLS:
        try:
            html = _get(url)
            rnk = _parse_rank_from_list(html, brand, model)
            if isinstance(rnk, int) and rnk > 0:
                print(f"[dxo] {brand} {model}: rank #{rnk} via list page {url}")
                return rnk
        except Exception as e:
            print(f"[dxo] list fetch failed {url}: {e}")

    # If all failed, None
    print(f"[dxo] {brand} {model}: rank not found")
    return None
