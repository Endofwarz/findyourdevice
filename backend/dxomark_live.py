# backend/dxomark_live.py
from __future__ import annotations
import os, re, json
from typing import Optional
import requests
from bs4 import BeautifulSoup

DXO_HEADERS = {
    "User-Agent": os.getenv(
        "DXO_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.dxomark.com/",
}

def _http_get(url: str, timeout: float = 15.0) -> str:
    r = requests.get(url, headers=DXO_HEADERS, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.text

def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")

def _build_url(brand: str, model: str) -> str:
    """Build canonical device URL."""
    b = brand.strip().replace(" ", "-")
    m = model.strip().replace(" ", "-")
    return f"https://www.dxomark.com/smartphones/{b}/{m}"

# -------------------- extractors --------------------

_ORD_RX = re.compile(
    r"(\d{1,3})\s*(?:st|nd|rd|th)\s+in\s+global\s+ranking",
    re.I,
)

def _extract_rank_from_global_text(html: str) -> Optional[int]:
    """
    Most reliable on current DXOMARK pages:
    e.g. '7TH in Global Ranking'
    """
    text = " ".join(_soup(html).get_text(" ", strip=True).split())
    m = _ORD_RX.search(text)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None

def _extract_rank_from_next_json(html: str) -> Optional[int]:
    """
    Some pages render rank inside Next.js __NEXT_DATA__.
    """
    tag = _soup(html).find("script", {"id": "__NEXT_DATA__"})
    if not tag or not tag.string:
        return None
    try:
        data = json.loads(tag.string)
    except Exception:
        return None

    def deep_find(obj, keys):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in keys and (isinstance(v, (int, str))):
                    return v
                found = deep_find(v, keys)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for v in obj:
                found = deep_find(v, keys)
                if found is not None:
                    return found
        return None

    val = deep_find(data, {"rankingPosition", "rank", "position"})
    if isinstance(val, int):
        return val
    if isinstance(val, str) and val.isdigit():
        return int(val)
    return None

def _extract_rank_from_ld_json(html: str) -> Optional[int]:
    """
    Rare fallback: some pages expose data in application/ld+json.
    """
    for tag in _soup(html).find_all("script", {"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        if isinstance(data, dict):
            txt = json.dumps(data)
        else:
            txt = json.dumps(data, ensure_ascii=False)
        m = _ORD_RX.search(txt)
        if m:
            return int(m.group(1))
    return None

# -------------------- public API --------------------

def fetch_dxomark_camera_rank(brand: str, model: str) -> Optional[int]:
    """
    Returns DXOMARK camera **rank** (int) for the given phone, or None.
    """
    if os.getenv("USE_DXOMARK_LIVE", "1") != "1":
        return None

    url = _build_url(brand, model)

    # Try the provided casing first, then a couple of friendly variants.
    candidates = [url]

    # Title-case brand/model (helps when caller passes lowercase)
    b_tc = " ".join(p.capitalize() for p in brand.split())
    m_tc = "-".join(p.capitalize() for p in model.replace("-", " ").split())
    candidates.append(_build_url(b_tc, m_tc))

    # Keep brand case, title-case model only
    candidates.append(_build_url(brand, m_tc))

    for u in dict.fromkeys(candidates):  # de-dup while preserving order
        try:
            html = _http_get(u)
        except Exception as e:
            print(f"[dxo] fetch failed {u}: {e}")
            continue

        # 1) Parse the visible '... in Global Ranking' line
        rank = _extract_rank_from_global_text(html)
        if rank:
            print(f"[dxo] {brand} {model}: rank #{rank} (Global text) {u}")
            return rank

        # 2) Fallback to Next.js data
        rank = _extract_rank_from_next_json(html)
        if rank:
            print(f"[dxo] {brand} {model}: rank #{rank} (NEXT_DATA) {u}")
            return rank

        # 3) Fallback to ld+json (rare)
        rank = _extract_rank_from_ld_json(html)
        if rank:
            print(f"[dxo] {brand} {model}: rank #{rank} (ld+json) {u}")
            return rank

    print(f"[dxo] {brand} {model}: rank not found {url}")
    return None

def diag_dxomark(brand: str, model: str):
    """Simple diagnostics endpoint payload."""
    url = _build_url(brand, model)
    out = {
        "brand": brand,
        "model": model,
        "url_tried": url,
        "env": {"USE_DXOMARK_LIVE": os.getenv("USE_DXOMARK_LIVE", "")},
    }
    try:
        out["result"] = fetch_dxomark_camera_rank(brand, model)
    except Exception as e:
        out["error"] = str(e)
    return out
