# backend/reddit_live.py
from __future__ import annotations
import re, time, requests
from typing import List, Dict, Tuple

UA = {"User-Agent": "findyourdevice-bot/0.1 by yourname"}
BASE = "https://www.reddit.com"

def _get_json(path: str, params: dict) -> dict:
    r = requests.get(f"{BASE}{path}", params=params, headers=UA, timeout=12)
    r.raise_for_status()
    return r.json()

def search_posts(brand: str, model: str, limit: int = 8) -> List[Dict]:
    """
    Uses Reddit's public JSON search (no OAuth). Rate-limited but fine for light use.
    """
    q = f'"{brand} {model}" review OR battery OR camera OR heating OR lag OR bug'
    j = _get_json("/search.json", {
        "q": q, "sort": "relevance", "t": "year", "type": "link", "limit": max(3, min(25, limit))
    })
    out = []
    for c in (j.get("data", {}).get("children") or []):
        d = c.get("data") or {}
        if d.get("subreddit_type") == "public" and not d.get("over_18"):
            out.append({
                "id": d.get("id"),
                "title": d.get("title",""),
                "url": d.get("url",""),
                "permalink": d.get("permalink",""),
                "score": d.get("score",0),
            })
    return out

def fetch_comments(post_id: str, max_chars: int = 6000) -> str:
    """
    Pulls the top-level comments text; trims to a safe size.
    """
    j = _get_json(f"/comments/{post_id}.json", {"limit": 100, "depth": 1, "sort": "top"})
    bodies = []
    if isinstance(j, list) and len(j) > 1:
        for child in (j[1].get("data",{}).get("children") or []):
            body = ((child.get("data") or {}).get("body") or "").strip()
            if body:
                bodies.append(body)
    text = "\n\n".join(bodies)
    return text[:max_chars]

def extract_pros_cons_plain(text: str) -> Tuple[List[str], List[str]]:
    """
    Lightweight heuristic extractor (works with your LLM path too).
    """
    t = text.lower()
    pros, cons = [], []
    def add(lst, s, cap):
        if s and s.lower() not in {x.lower() for x in lst} and len(lst) < cap:
            lst.append(s)
    # very rough signals
    if "battery" in t: add(pros, "Good battery life reported by owners", 6)
    if "camera" in t: add(pros, "Owners like camera quality in daylight", 6)
    if "display" in t or "screen" in t: add(pros, "Nice, bright display", 6)
    if "software" in t or "updates" in t: add(pros, "Software/updates praised in threads", 6)

    if "overheat" in t or "heating" in t or "hot" in t: add(cons, "Some users report heating under load", 5)
    if "bug" in t or "crash" in t: add(cons, "Occasional software bugs mentioned", 5)
    if "battery drain" in t or "drain" in t: add(cons, "Battery drain reported by some", 5)
    if "lag" in t or "stutter" in t: add(cons, "Lag/stutter for a few users", 5)
    return pros, cons

def summarize_reddit(brand: str, model: str, max_posts: int = 5) -> Tuple[List[str], List[str], List[str]]:
    """
    Returns (pros, cons, sources). Non-LLM heuristics; your main app may refine with LLM.
    """
    posts = search_posts(brand, model, limit=max_posts)
    if not posts:
        return [], [], []
    texts, sources = [], []
    for p in posts[:max_posts]:
        try:
            texts.append(fetch_comments(p["id"]))
            sources.append(BASE + p["permalink"])
            time.sleep(0.25)
        except Exception:
            pass
    joined = "\n\n".join([t for t in texts if t.strip()])
    if not joined:
        return [], [], sources
    pros, cons = extract_pros_cons_plain(joined)
    return pros, cons, sources
