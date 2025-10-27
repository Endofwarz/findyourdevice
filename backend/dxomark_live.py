# backend/dxomark_live.py
from __future__ import annotations
import os, re
from typing import Optional
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

RANK_LIST_URLS = [
    "https://www.dxomark.com/smartphones/smartphone-ranking/",
    "https://www.dxomark.com/smartphones/",
]

def _http_get(url: str, timeout: float = 10.0) -> str:
    r = requests.get(url, headers=DXO_HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.text

def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")

def _normalize_title(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip().lower()
    return s

def _tokenize(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _normalize_title(s)))

def _candidate_keys(brand: str, model: str) -> list[str]:
    b = _normalize_title(brand)
    m = _normalize_title(model)
    keys = [f"{b} {m}", m]
    if b == "apple" and not m.startswith("iphone"):
        keys.append(f"iphone {m}")
    if b == "samsung" and not m.startswith("galaxy"):
        keys.append(f"galaxy {m}")
    return [k.strip() for k in keys]

def _best_row_match(rows, brand: str, model: str) -> Optional[int]:
    cand_keys = _candidate_keys(brand, model)
    cand_sets = [_tokenize(k) for k in cand_keys]
    for rank, title in rows:
        tset = _tokenize(title)
        for cset in cand_sets:
            if cset and cset.issubset(tset):
                return rank
    return None

def _parse_ranking_list(html: str) -> list[tuple[int, str]]:
    s = _soup(html)
    rows: list[tuple[int, str]] = []

    # Layout A: explicit rank numbers
    for tr in s.select("table tr"):
        txt = " ".join(tr.get_text(" ", strip=True).split())
        m = re.search(r"^\s*(\d+)\s*\.\s*(.+)$", txt)
        if m:
            rank = int(m.group(1))
            title = m.group(2)
            rows.append((rank, title))

    # Layout B: list or card format
    for li in s.select("li, div"):
        rank_el = li.select_one(".rank, .c-ranking__position, .c-listing__position")
        name_el = li.select_one(".device, .c-card__title, .c-listing__title, h3, h2")
        if rank_el and name_el:
            try:
                rank = int(re.sub(r"[^\d]", "", rank_el.get_text()))
            except Exception:
                continue
            title = " ".join(name_el.get_text(" ", strip=True).split())
            if rank and title:
                rows.append((rank, title))

    # Deduplicate by rank
    seen = set()
    out = []
    for r, t in rows:
        if r not in seen:
            out.append((r, t))
            seen.add(r)
    return out

def fetch_dxomark_camera_rank(brand: str, model: str) -> Optional[int]:
    """
    Try to find the DXOMARK camera rank.
    """
    if os.getenv("USE_DXOMARK_LIVE", "1") != "1":
        return None

    # 1) Try list pages
    for url in RANK_LIST_URLS:
        try:
            html = _http_get(url, timeout=12)
            rows = _parse_ranking_list(html)
            if rows:
                rnk = _best_row_match(rows, brand, model)
                if rnk:
                    print(f"[dxo] {brand} {model}: rank #{rnk} via list page {url}")
                    return rnk
        except Exception as e:
            print(f"[dxo] list fetch failed {url}: {e}")

    # 2) Fallback: device page
    slug = re.sub(r"\s+", "-", _normalize_title(f"{brand} {model}"))
    for u in [
        f"https://www.dxomark.com/{slug}-camera/",
        f"https://www.dxomark.com/{slug}/",
    ]:
        try:
            html = _http_get(u, timeout=10)
            text = " ".join(_soup(html).get_text(" ", strip=True).split())
            m = re.search(r"Overall ranking\s*#\s*(\d+)", text, re.I)
            if m:
                print(f"[dxo] {brand} {model}: rank #{m.group(1)} via device page")
                return int(m.group(1))
        except Exception:
            continue

    print(f"[dxo] {brand} {model}: rank not found")
    return None

# --- diagnostics helper (used by /dxo/diag) ----------------------------------

def diag_dxomark(brand: str, model: str):
    info = {
        "brand": brand,
        "model": model,
        "env": {"USE_DXOMARK_LIVE": os.getenv("USE_DXOMARK_LIVE", "")},
        "notes": [],
    }
    try:
        rnk = fetch_dxomark_camera_rank(brand, model)
        info["result"] = rnk
    except Exception as e:
        info["error"] = str(e)

    try:
        html = _http_get(RANK_LIST_URLS[0], timeout=8)
        sample = " ".join(_soup(html).get_text(" ", strip=True).split()[:30])
        info["text_sample"] = sample[:500]
    except Exception:
        pass

    return info
