# backend/dxomark_live.py
from __future__ import annotations
import os, re, json
from typing import Optional
import requests
from bs4 import BeautifulSoup

DXO_HEADERS = {
    "User-Agent": os.getenv("DXO_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.dxomark.com/",
}

def _http_get(url: str, timeout: float = 12.0) -> str:
    r = requests.get(url, headers=DXO_HEADERS, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.text

def _soup(html_text: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html_text, "lxml")
    except Exception:
        return BeautifulSoup(html_text, "html.parser")

def _build_url(brand: str, model: str) -> str:
    """
    Build canonical DXOMARK smartphone URL using new format:
    https://www.dxomark.com/smartphones/<Brand>/<Model>
    Example: Apple / iPhone-16-Pro-Max
    """
    b = brand.strip().replace(" ", "-")
    m = model.strip().replace(" ", "-")
    return f"https://www.dxomark.com/smartphones/{b}/{m}"

def _extract_rank_from_json(html_text: str) -> Optional[int]:
    """
    Parses rank from DXOMARK's __NEXT_DATA__ JSON payload.
    Usually under props.pageProps.device.rankings.camera.overall.position or similar.
    """
    soup = _soup(html_text)
    tag = soup.find("script", {"id": "__NEXT_DATA__"})
    if not tag:
        return None
    try:
        data = json.loads(tag.string)
    except Exception:
        return None

    def deep_find(obj, key):
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for v in obj.values():
                found = deep_find(v, key)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for v in obj:
                found = deep_find(v, key)
                if found is not None:
                    return found
        return None

    # Try common key paths
    for k in ("rankingPosition", "rank", "position"):
        val = deep_find(data, k)
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
    return None

def _extract_rank_fallback_text(html_text: str) -> Optional[int]:
    """
    Fallback for rare cases: visible 'Overall ranking #7'
    """
    text = " ".join(_soup(html_text).get_text(" ", strip=True).split())
    m = re.search(r"ranking[^#]{0,20}#\s*(\d{1,3})", text, re.I)
    if m:
        return int(m.group(1))
    return None

def fetch_dxomark_camera_rank(brand: str, model: str) -> Optional[int]:
    """
    Returns DXOMARK camera rank (int) for the given phone, or None.
    """
    if os.getenv("USE_DXOMARK_LIVE", "1") != "1":
        return None

    url = _build_url(brand, model)
    try:
        html_text = _http_get(url)
    except Exception as e:
        print(f"[dxo] fetch failed {url}: {e}")
        return None

    # Try modern JSON structure
    rank = _extract_rank_from_json(html_text)
    if rank:
        print(f"[dxo] {brand} {model}: rank #{rank} (JSON) {url}")
        return rank

    # Fallback visible text
    rank = _extract_rank_fallback_text(html_text)
    if rank:
        print(f"[dxo] {brand} {model}: rank #{rank} (text) {url}")
        return rank

    print(f"[dxo] {brand} {model}: rank not found {url}")
    return None

# --- diagnostics helper -------------------------------------------------------

def diag_dxomark(brand: str, model: str):
    info = {
        "brand": brand,
        "model": model,
        "url": _build_url(brand, model),
        "env": {"USE_DXOMARK_LIVE": os.getenv("USE_DXOMARK_LIVE", "")},
    }
    try:
        rnk = fetch_dxomark_camera_rank(brand, model)
        info["result"] = rnk
    except Exception as e:
        info["error"] = str(e)
    return info
