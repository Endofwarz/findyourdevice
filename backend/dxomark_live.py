# backend/dxomark_live.py
from __future__ import annotations
import os, re
from typing import Optional, List
import requests
from bs4 import BeautifulSoup

DXO_HEADERS = {
    "User-Agent": os.getenv("DXO_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://www.dxomark.com/",
}

def _http_get(url: str, timeout: float = 12.0, headers: dict | None = None) -> str:
    r = requests.get(url, headers=headers or DXO_HEADERS, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.text

def _soup(html_text: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html_text, "lxml")
    except Exception:
        return BeautifulSoup(html_text, "html.parser")

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()

def _slug(brand: str, model: str) -> str:
    nm = _norm(f"{brand} {model}")
    return re.sub(r"[^a-z0-9]+", "-", nm).strip("-")

# --- WordPress search to find the exact device URL ----------------------------

def _wp_search_urls(brand: str, model: str, limit: int = 8) -> List[str]:
    q = f"{brand} {model}"
    url = f"https://www.dxomark.com/wp-json/wp/v2/search?search={requests.utils.quote(q)}&per_page={limit}"
    try:
        js = requests.get(url, headers=DXO_HEADERS, timeout=10).json()
    except Exception as e:
        print("[dxo] wp search failed:", e)
        return []
    urls = []
    for row in js or []:
        href = row.get("url") or row.get("link") or ""
        if not href:
            continue
        # Prefer smartphone/camera pages
        if any(x in href for x in ("/smartphones/", "-camera", "-camera-review", "-camera-test")):
            urls.append(href)
    # de-dupe while preserving order
    out, seen = [], set()
    for u in urls:
        if u not in seen:
            out.append(u); seen.add(u)
    return out

# --- Extractors from device page ---------------------------------------------

_RANK_TEXT_PATTERNS = [
    r"(?:overall|global)\s+ranking\s*#\s*(\d{1,3})",
    r"ranking[^#]{0,20}#\s*(\d{1,3})",
    r"#\s*(\d{1,3})\s*(?:in\s*our\s*ranking|overall\s*ranking)",
    r"\brank\s*#\s*(\d{1,3})\b",
]

_SCRIPT_PATTERNS = [
    r'"rankingPosition"\s*:\s*(\d{1,3})',
    r"'rankingPosition'\s*:\s*(\d{1,3})",
    r'"cameraRanking"\s*:\s*{[^}]*"position"\s*:\s*(\d{1,3})',
]

_ATTR_PATTERNS = [
    r'data-ranking-position\s*=\s*"(\d{1,3})"',
    r'data-rank\s*=\s*"(\d{1,3})"',
]

def _extract_rank_from_html(html_text: str) -> Optional[int]:
    # 1) try inline scripts first (most reliable lately)
    for pat in _SCRIPT_PATTERNS:
        m = re.search(pat, html_text, re.I)
        if m:
            try: return int(m.group(1))
            except: pass
    # 2) try data-* attributes
    for pat in _ATTR_PATTERNS:
        m = re.search(pat, html_text, re.I)
        if m:
            try: return int(m.group(1))
            except: pass
    # 3) fallback to visible text
    text = " ".join(_soup(html_text).get_text(" ", strip=True).split())
    for pat in _RANK_TEXT_PATTERNS:
        m = re.search(pat, text, re.I)
        if m:
            try: return int(m.group(1))
            except: pass
    return None

def _try_device_pages(brand: str, model: str) -> Optional[int]:
    # Attempt obvious slugs first (fast path)
    slug = _slug(brand, model)
    candidates = [
        f"https://www.dxomark.com/{slug}-camera/",
        f"https://www.dxomark.com/smartphones/{slug}-camera-review/",
        f"https://www.dxomark.com/smartphones/{slug}-camera-test/",
        f"https://www.dxomark.com/smartphones/{slug}/",
        f"https://www.dxomark.com/{slug}/",
    ]
    for url in candidates:
        try:
            html_text = _http_get(url, timeout=10)
            rnk = _extract_rank_from_html(html_text)
            if rnk:
                print(f"[dxo] rank via device slug {url}: #{rnk}")
                return rnk
        except Exception:
            continue
    return None

def _try_wp_search_then_parse(brand: str, model: str) -> Optional[int]:
    for url in _wp_search_urls(brand, model):
        try:
            html_text = _http_get(url, timeout=10)
            rnk = _extract_rank_from_html(html_text)
            if rnk:
                print(f"[dxo] rank via wp search {url}: #{rnk}")
                return rnk
        except Exception:
            continue
    return None

# --- Public API ---------------------------------------------------------------

def fetch_dxomark_camera_rank(brand: str, model: str) -> Optional[int]:
    """
    Returns 1-based DXOMARK camera rank for the given phone, or None.
    Strategy:
      1) Device slug pages
      2) WordPress search -> device page -> parse inline JSON / attributes / text
    """
    if os.getenv("USE_DXOMARK_LIVE", "1") != "1":
        return None

    rnk = _try_device_pages(brand, model)
    if rnk:
        return rnk
    rnk = _try_wp_search_then_parse(brand, model)
    if rnk:
        return rnk

    print(f"[dxo] {_norm(brand)} {_norm(model)}: rank not found")
    return None

def diag_dxomark(brand: str, model: str):
    """
    Diagnostic payload to call from /dxo/diag
    """
    info = {
        "brand": brand,
        "model": model,
        "env": {"USE_DXOMARK_LIVE": os.getenv("USE_DXOMARK_LIVE", "")},
    }
    try:
        info["result"] = fetch_dxomark_camera_rank(brand, model)
    except Exception as e:
        info["error"] = str(e)
    try:
        # Include one WP search hit to prove connectivity
        info["wp_search_urls"] = _wp_search_urls(brand, model)[:3]
    except Exception:
        pass
    return info
