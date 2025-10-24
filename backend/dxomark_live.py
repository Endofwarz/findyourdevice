# backend/dxomark.py
from __future__ import annotations
import re, requests
from bs4 import BeautifulSoup
from typing import Tuple, Optional

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; findyourdevice/1.0)"}
RANK_URL = "https://www.dxomark.com/smartphones/"

def _norm(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip().lower()
    s = s.replace("apple ", "").replace("samsung ", "").replace("google ", "")
    s = s.replace("oneplus ", "").replace("xiaomi ", "").replace("sony ", "")
    s = s.replace("motorola ", "").replace("nothing ", "")
    return s

def fetch_dxomark_camera_rank(brand: str, model: str) -> Tuple[Optional[int], Optional[float]]:
    """
    Returns (rank, score) if the device appears on the DxOMARK smartphones
    ranking page; otherwise (None, None).
    """
    try:
        r = requests.get(RANK_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print("[dxo] fetch fail:", e)
        return None, None

    target = _norm(f"{brand} {model}")
    rank = None
    score = None

    # Page structure can change; be tolerant:
    # Look for list/grid items that contain model name and a numeric score.
    cards = soup.select("a, div")
    best = None
    for i, node in enumerate(cards, start=1):
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
        low = text.lower()
        if not low: 
            continue
        if any(k in low for k in [brand.lower(), model.lower()]):
            # find a score like 123 or 123.4 near it
            m = re.search(r"(\d{2,3}(?:\.\d)?)", text)
            sc = float(m.group(1)) if m else None
            nm = _norm(text)
            # choose closest name
            if target in nm or model.lower() in nm:
                best = (i, sc)
                break

    if best:
        rank, score = best[0], best[1]
    return rank, score
