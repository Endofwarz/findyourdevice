# backend/dxomark_live.py
from __future__ import annotations
import re, time, requests
from bs4 import BeautifulSoup
from typing import Optional

UA = {"User-Agent": "findyourdevice-bot/0.1"}

def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")

def _get(url: str) -> str:
    r = requests.get(url, headers=UA, timeout=15)
    r.raise_for_status()
    return r.text

def _first_result_url(brand: str, model: str) -> Optional[str]:
    # DXOMARK site search
    q = f"{brand} {model}".strip().replace(" ", "+")
    html = _get(f"https://www.dxomark.com/?s={q}")
    soup = _soup(html)
    a = soup.select_one("h3.entry-title a")
    if a and a.get("href"):
        return a["href"]
    return None

def _parse_score_from_page(html: str) -> Optional[int]:
    # try common patterns seen on device pages
    text = _soup(html).get_text(" ", strip=True)
    # e.g., "DXOMARK Camera score: 152"
    m = re.search(r"Camera score:\s*(\d{2,3})", text, re.I)
    if m: return int(m.group(1))
    m = re.search(r"DXOMARK\s+Camera\s+score\s+(\d{2,3})", text, re.I)
    if m: return int(m.group(1))
    # some pages have "Overall score" next to camera
    m = re.search(r"Overall\s+Camera\s+score\s*(\d{2,3})", text, re.I)
    if m: return int(m.group(1))
    return None

def fetch_dxomark_camera_score(brand: str, model: str) -> Optional[int]:
    url = _first_result_url(brand, model)
    if not url:
        return None
    html = _get(url)
    score = _parse_score_from_page(html)
    return score
