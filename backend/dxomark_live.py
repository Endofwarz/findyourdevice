# backend/dxomark_live.py
from __future__ import annotations
import os, re
from typing import Optional
import requests
from bs4 import BeautifulSoup

BASE = "https://www.dxomark.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; findyourdevice/0.1)"}

def _html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

def fetch_dxomark_camera_rank(brand: str, model: str) -> Optional[int]:
    # Pull the main smartphone ranking page
    try:
        html = _html(f"{BASE}/smartphones/")
    except Exception as e:
        print("[dxo] fetch page failed:", e)
        return None

    soup = BeautifulSoup(html, "lxml")
    want = _norm(f"{brand} {model}")

    rank_found = None
    # Each product card usually has data like rank and a title link
    for card in soup.select("div.card-product, article.card-product"):
        title_el = card.select_one("a, h3, h2")
        if not title_el: 
            continue
        title = _norm(title_el.get_text(" ", strip=True))
        if not title:
            continue

        # cheap fuzzy match
        if all(tok in title for tok in _norm(brand).split()):
            if any(tok in title for tok in _norm(model).split()):
                # rank appears in badges or as numeric label
                txt = card.get_text(" ", strip=True).lower()
                # try common patterns like "#12", "rank 12", or "n° 12"
                m = re.search(r"(?:#|\brank\b|\bn[°o]\b)\s*(\d{1,3})", txt, re.I)
                if not m:
                    # some cards show position near the left badge
                    m = re.search(r"\b(\d{1,3})\b.*(?:camera|smartphone)", txt, re.I)
                if m:
                    try:
                        rank_found = int(m.group(1))
                        break
                    except Exception:
                        pass

    return rank_found
