# backend/dxomark_live.py
from __future__ import annotations
import os, re, html
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

SEARCH_HEADERS = {
    "User-Agent": DXO_HEADERS["User-Agent"],
    "Accept-Language": DXO_HEADERS["Accept-Language"],
    "Referer": "https://duckduckgo.com/",
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
    s = re.sub(r"\s+", " ", (s or "").strip()).lower()
    return s

def _slug(brand: str, model: str) -> str:
    nm = _norm(f"{brand} {model}")
    return re.sub(r"[^a-z0-9]+", "-", nm).strip("-")

def _extract_rank_from_text(text: str) -> Optional[int]:
    # Try a few phrasings we’ve seen on DXOMARK device pages
    patterns = [
        r"(?:overall|global)\s+ranking\s*#\s*(\d{1,3})",
        r"ranking[^#]{0,20}#\s*(\d{1,3})",
        r"#\s*(\d{1,3})\s*(?:in\s*our\s*ranking|overall\s*ranking)"
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None

def _try_device_pages(brand: str, model: str) -> Optional[int]:
    slug = _slug(brand, model)
    candidates = [
        f"https://www.dxomark.com/{slug}-camera/",
        f"https://www.dxomark.com/smartphones/{slug}-camera-test/",
        f"https://www.dxomark.com/smartphones/{slug}-camera-review/",
        f"https://www.dxomark.com/smartphones/{slug}/",
        f"https://www.dxomark.com/{slug}/",
    ]
    for url in candidates:
        try:
            html_text = _http_get(url, timeout=10)
            text = " ".join(_soup(html_text).get_text(" ", strip=True).split())
            rnk = _extract_rank_from_text(text)
            if rnk:
                print(f"[dxo] {brand} {model}: rank #{rnk} via device page {url}")
                return rnk
        except Exception:
            continue
    return None

def _ddg_search_dxomark(brand: str, model: str) -> List[str]:
    """
    Use DuckDuckGo's HTML endpoint (no JS, no API key) to find relevant DXOMARK URLs.
    """
    q = f'site:dxomark.com "{brand} {model}" camera'
    url = "https://duckduckgo.com/html/?q=" + requests.utils.quote(q)
    try:
        html_text = _http_get(url, timeout=10, headers=SEARCH_HEADERS)
    except Exception as e:
        print("[dxo] ddg search failed:", e)
        return []
    s = _soup(html_text)
    links = []
    # DDG HTML puts results in .result__a, but we’ll be tolerant
    for a in s.select("a.result__a, a[href]"):
        href = a.get("href") or ""
        # DDG sometimes wraps URLs like "/l/?kh=-1&uddg=<urlencoded>"
        # unwrap if needed
        if "/l/?" in href and "uddg=" in href:
            m = re.search(r"uddg=([^&]+)", href)
            if m:
                href = requests.utils.unquote(m.group(1))
        if "dxomark.com" in href:
            # Prefer smartphone/camera pages
            if any(x in href for x in ("/smartphones/", "-camera", "-camera-review", "-camera-test")):
                links.append(href)
    # Deduplicate & limit
    out = []
    seen = set()
    for u in links:
        if u not in seen:
            out.append(u)
            seen.add(u)
        if len(out) >= 6:
            break
    return out

def _try_search_then_parse(brand: str, model: str) -> Optional[int]:
    for url in _ddg_search_dxomark(brand, model):
        try:
            html_text = _http_get(url, timeout=10)
            text = " ".join(_soup(html_text).get_text(" ", strip=True).split())
            rnk = _extract_rank_from_text(text)
            if rnk:
                print(f"[dxo] {brand} {model}: rank #{rnk} via search result {url}")
                return rnk
        except Exception:
            continue
    return None

def fetch_dxomark_camera_rank(brand: str, model: str) -> Optional[int]:
    """
    Returns 1-based DXOMARK camera rank for the given phone, or None.
    Strategy:
      1) Try device-page slugs directly (fast path)
      2) If not found, search for the device page using DDG HTML and parse
    """
    if os.getenv("USE_DXOMARK_LIVE", "1") != "1":
        return None

    # 1) Device pages
    rnk = _try_device_pages(brand, model)
    if rnk:
        return rnk

    # 2) Search-based fallback
    rnk = _try_search_then_parse(brand, model)
    if rnk:
        return rnk

    print(f"[dxo] {brand} {model}: rank not found")
    return None

# --- diagnostics helper -------------------------------------------------------

def diag_dxomark(brand: str, model: str):
    info = {
        "brand": brand,
        "model": model,
        "env": {"USE_DXOMARK_LIVE": os.getenv("USE_DXOMARK_LIVE", "")},
    }
    try:
        info["result"] = fetch_dxomark_camera_rank(brand, model)
    except Exception as e:
        info["error"] = str(e)

    # Include a small snippet from a search page to prove connectivity
    try:
        q_url = "https://duckduckgo.com/html/?q=" + requests.utils.quote(f'site:dxomark.com "{brand} {model}" camera')
        html_text = _http_get(q_url, timeout=6, headers=SEARCH_HEADERS)
        sample = " ".join(_soup(html_text).get_text(" ", strip=True).split()[:30])
        info["ddg_text_sample"] = sample[:400]
    except Exception:
        pass
    return info
