from __future__ import annotations
from amazon_live import fetch_amazon_offer
from dxomark_live import cached_dxomark_rank  # make sure this exists
from gsma_scraper import fetch_specs_live, fetch_price_live, fetch_gallery_urls
import traceback
from gsma_scraper import fetch_specs_live, ScrapeError
from config import PHONES_CSV, USE_LLM, ALLOW_SCRAPERS, DEMO_SEED
import random
if DEMO_SEED:
    try: random.seed(int(DEMO_SEED))
    except: random.seed(42)
import os, re, json, uuid, math
USE_GSMA_LIVE = os.getenv("USE_GSMA_LIVE", "1") == "1"
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd, pathlib, csv, os
import requests           
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request
from fastapi import HTTPException, Query
import time as _time  # safe alias; we also use _time for yt sleeps
DIAG = os.getenv("DIAG", "1") == "1"   # turn off by setting DIAG=0
EUR_PER_USD = float(os.getenv("FX_EUR_PER_USD", "0.93"))
from reddit_live import reddit_search_pros_cons  # add at top
from dxomark_live import fetch_dxomark_camera_rank
USE_REDDIT_LIVE = os.getenv("USE_REDDIT_LIVE", "1") == "1"
USE_DXOMARK_LIVE = os.getenv("USE_DXOMARK_LIVE", "1") == "1"

# --- Safe client IP helper (define BEFORE endpoints) ---
def _client_ip(request: Request) -> str:
    try:
        # Prefer the actual connection
        c = getattr(request, "client", None)
        if c and getattr(c, "host", None):
            return c.host
        # Respect proxies/load balancers if present
        xfwd = None
        try:
            xfwd = request.headers.get("x-forwarded-for")
        except Exception:
            xfwd = None
        if xfwd:
            first = (xfwd.split(",")[0] or "").strip()
            if first:
                return first
    except Exception:
        pass
    return "unknown"

app = FastAPI(title="Phone Finder API", version="2.0")

from llm import chat_complete
from prompts import blurb_messages, pros_cons_messages
ALLOWED_ORIGINS = [
  "http://127.0.0.1:5173",
  "http://localhost:5173",
  "https://findyourdevice.vercel.app",
]

@app.get("/")
def root():
    return {"ok": True, "docs": "/docs", "health": "/healthz"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
from pydantic import BaseModel
from fastapi import Request

from fastapi import FastAPI
from reddit_live import reddit_diag, reddit_search_pros_cons

app = FastAPI()

@app.get("/reddit/diag")
def reddit_diag_api(brand: str = "Apple", model: str = "16 Pro Max"):
    return reddit_diag(brand, model)

# (Optional) keep your existing /reddit/test but make it return json with detail
@app.get("/reddit/test")
def reddit_test_api(brand: str, model: str):
    try:
        pros, cons = reddit_search_pros_cons(brand, model)
        return {"ok": True, "brand": brand, "model": model, "pros": pros, "cons": cons}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# near other imports
from dxomark_live import fetch_dxomark_camera_rank, diag_dxomark

# --- quick test/diag endpoints ---
@app.get("/dxo/test")
def dxo_test(brand: str, model: str):
    score = fetch_dxomark_camera_rank(brand, model)
    return {"ok": True, "brand": brand, "model": model, "camera_rank": score}

@app.get("/dxo/diag")
def dxo_diag(brand: str, model: str):
    return diag_dxomark(brand, model)

@app.get("/llm/price_test")
def llm_price_test(brand: str, model: str):
    if not USE_LLM:
        return {"ok": False, "reason": "USE_LLM=0"}
    price, url = fetch_price_with_llm(brand, model)
    return {"ok": True, "brand": brand, "model": model, "price": price, "url": url}

@app.get("/techspecs/image_test")
def techspecs_image_test(brand: str, model: str):
    if not TECHSPECS_API_KEY:
        return {"ok": False, "reason": "TECHSPECS_API_KEY not set"}
    urls = fetch_images_from_techspecs(brand, model)
    return {"ok": True, "brand": brand, "model": model, "image_urls": urls}

@app.get("/google_cse/image_test")
def google_cse_image_test(brand: str, model: str):
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        return {"ok": False, "reason": "GOOGLE_CSE_API_KEY or GOOGLE_CSE_CX not set"}
    urls = fetch_images_from_google_cse(brand, model)
    return {"ok": True, "brand": brand, "model": model, "image_urls": urls}


import csv, pathlib

GSMA_OUT = os.getenv("GSMA_OUT", "data/processed/phones_gsma.csv")
GSMA_PATH = os.getenv("PHONES_CSV", "data/processed/phones_gsma.csv")
LEGACY_PATH = "data/processed/phones_clean.csv"

def _safe_csv_path():
    p = GSMA_PATH
    try:
        if os.path.exists(p) and os.path.getsize(p) > 200:  # crude "non-empty" check
            import pandas as _pd
            df = _pd.read_csv(p, nrows=5)
            if df.shape[1] >= 6:  # also check it looks like a CSV
                return p
    except Exception:
        pass
    # fallback
    return LEGACY_PATH

def _usd_to_eur(v):
    try:
        return round(float(v) * EUR_PER_USD, 2) if v is not None else None
    except Exception:
        return None
CSV_PATH = _safe_csv_path()

EUR_PER_SEK = float(os.getenv("FX_EUR_PER_SEK", "0.089"))  # ungefärlig kurs

def _sek_to_eur(v):
    try:
        return round(float(v) * EUR_PER_SEK, 2)
    except Exception:
        return None


# choose GSMA as default if present; fall back to your old CSV
PHONES_CSV = os.getenv("PHONES_CSV", GSMA_OUT if os.path.exists(GSMA_OUT)
                                       else "data/processed/phones_clean.csv")

@app.on_event("startup")
def _seed_gsma_if_missing():
    try:
        if os.getenv("IMPORT_ON_BOOT", "1") == "1" and not os.path.exists(GSMA_OUT):
            from gsma_scraper import bootstrap_import
            brands = os.getenv("GSMA_BRANDS", "Apple,Samsung,Google,OnePlus,Sony,Motorola,Nothing").strip()
            min_year = int(os.getenv("GSMA_MIN_YEAR", "2023"))
            print(f"[startup] building GSMA CSV for: {brands} (>= {min_year})")
            bootstrap_import(GSMA_OUT, brands, min_year)
            # If PHONES_CSV wasn't set explicitly, the next load_df() will pick it up
    except Exception as e:
        print("[startup] GSMA bootstrap failed:", e)

# --- Simple gallery fetcher (Wikimedia first, fallback to Wikipedia thumb) ---
def fetch_phone_gallery(brand: str, model: str, limit: int = 4) -> list[str]:
    """
    Returns a few safe, hotlinkable image URLs (ideally front/back/side).
    Strategy:
      1) Wikimedia commons search for "<brand> <model>" and take first images.
      2) Fallback to Wikipedia pageimage thumbnail.
    """
    import requests, re, html
    q = f"{brand} {model}"
    out = []

    # (1) Wikimedia Commons search (images + imageinfo)
    try:
        sr = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "prop": "imageinfo",
                "generator": "search",
                "gsrsearch": q,
                "gsrnamespace": 6,     # File:
                "gsrlimit": max(3, min(8, limit+2)),
                "iiprop": "url",
                "iiurlwidth": 1024,
            },
            timeout=10,
        )
        j = sr.json()
        pages = (j.get("query", {}) or {}).get("pages", {}) or {}
        # Prefer PNG/JPG phone-like filenames
        def score(name: str) -> int:
            n = name.lower()
            s = 0
            if "iphone" in n or "galaxy" in n or brand.lower() in n or model.lower() in n: s += 3
            if "front" in n or "back" in n or "side" in n: s += 2
            if n.endswith((".jpg", ".jpeg", ".png")): s += 1
            return s
        pics = []
        for p in pages.values():
            title = p.get("title","")
            ii = (p.get("imageinfo") or [{}])[0]
            url = ii.get("thumburl") or ii.get("url")
            if url:
                pics.append((score(title), url))
        pics.sort(reverse=True)
        out = [u for _, u in pics][:limit]
    except Exception:
        pass

    # (2) Fallback to Wikipedia pageimage
    if not out:
        try:
            title = q.strip()
            r = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query", "prop": "pageimages",
                    "format": "json", "pithumbsize": "1024", "titles": title
                },
                timeout=8,
            )
            data = r.json().get("query", {}).get("pages", {})
            for _, page in data.items():
                t = (page.get("thumbnail") or {}).get("source")
                if t:
                    out.append(t)
                    break
        except Exception:
            pass

    # final de-dupe
    seen, uniq = set(), []
    for u in out:
        if u and u not in seen:
            seen.add(u); uniq.append(u)
    return uniq[:limit]

def fetch_images_from_techspecs(brand: str, model: str, limit: int = 3) -> list[str]:
    """
    Fetches image URLs for a phone from the TechSpecs API.
    Prioritizes front, back, and side views.
    """
    if not TECHSPECS_API_KEY or not TECHSPECS_API_ID:
        print("[techspecs] API key or ID not set.")
        return []

    headers = {
        "X-API-ID": TECHSPECS_API_ID,
        "X-API-Key": TECHSPECS_API_KEY,
        "accept": "application/json"
    }
    search_query = f"{brand} {model}"
    url = f"https://api.techspecs.io/v5/products/search?query={quote_plus(search_query)}"

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        products = data.get("data", [])
        if not products:
            print(f"[techspecs] No products found for {brand} {model}")
            return []

        # The API returns a list of products, we need to find the best match
        # For now, we'll take the first one, but this could be improved
        product_id = products[0].get("id")
        if not product_id:
            print(f"[techspecs] No product ID found for {brand} {model}")
            return []

        # Now fetch the product details to get the images
        product_url = f"https://api.techspecs.io/v5/products/{product_id}"
        product_response = requests.get(product_url, headers=headers, timeout=10)
        product_response.raise_for_status()
        product_data = product_response.json()

        images = product_data.get("data", {}).get("images", [])
        if not images:
            print(f"[techspecs] No images found for {brand} {model}")
            return []

        gallery_urls = []
        keywords = {"front": None, "back": None, "side": None}
        for img in images:
            img_url = img.get("url")
            if not img_url:
                continue
            label = img.get("label", "").lower() or img_url.lower()

            if "front" in label and not keywords["front"]:
                keywords["front"] = img_url
            elif "back" in label and not keywords["back"]:
                keywords["back"] = img_url
            elif "side" in label and not keywords["side"]:
                keywords["side"] = img_url
            else:
                gallery_urls.append(img_url)

        final_images = []
        if keywords["front"]: final_images.append(keywords["front"])
        if keywords["back"]: final_images.append(keywords["back"])
        if keywords["side"]: final_images.append(keywords["side"])

        for img_url in gallery_urls:
            if len(final_images) < limit:
                final_images.append(img_url)
            else:
                break
        return final_images[:limit]

    except requests.exceptions.RequestException as e:
        print(f"[techspecs] API request failed for {brand} {model}: {e}")
    except Exception as e:
        print(f"[techspecs] Error processing TechSpecs response for {brand} {model}: {e}")
    return []

def fetch_images_from_google_cse(brand: str, model: str, limit: int = 3) -> list[str]:
    """
    Fetches image URLs for a phone from Google Custom Search Engine.
    Prioritizes front, back, and side views.
    """
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        print("[google_cse] API key or CX not set.")
        return []

    base_url = "https://www.googleapis.com/customsearch/v1"
    image_urls = []
    search_terms = [f"{brand} {model} front", f"{brand} {model} back", f"{brand} {model} side"]

    for term in search_terms:
        params = {
            "key": GOOGLE_CSE_API_KEY,
            "cx": GOOGLE_CSE_CX,
            "q": term,
            "searchType": "image",
            "num": 1, # Request only one image per search term
            "imgSize": "large", # Prefer large images
            "imgType": "photo", # Prefer photos
        }
        try:
            response = requests.get(base_url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()

            items = data.get("items", [])
            if items:
                # Take the first image URL found
                image_urls.append(items[0].get("link"))
                if len(image_urls) >= limit:
                    break
        except requests.exceptions.RequestException as e:
            print(f"[google_cse] API request failed for '{term}': {e}")
        except Exception as e:
            print(f"[google_cse] Error processing response for '{term}': {e}")

    # Filter out any None values and return up to the limit
    return [url for url in image_urls if url][:limit]



# ------------------ YouTube live fetch + CSV cache ------------------
# Requires: env var YOUTUBE_API_KEY (YouTube Data API v3 enabled)
# Optional: python package `youtube-transcript-api` for captions (auto-handled if missing)

import pathlib, csv, time as _time
from datetime import datetime, timedelta

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
TECHSPECS_API_KEY = os.getenv("TECHSPECS_API_KEY", "").strip()
TECHSPECS_API_ID = os.getenv("TECHSPECS_API_ID", "").strip()
GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "").strip()
GOOGLE_CSE_CX = os.getenv("GOOGLE_CSE_CX", "").strip()

_REVIEWS_CSV = pathlib.Path("data/processed/reviews.csv")
_REVIEWS_CSV.parent.mkdir(parents=True, exist_ok=True)

# Keep cache fresh for 30 days
_YT_TTL_DAYS = 30


def _yt_http(path: str, params: dict, timeout=12) -> tuple[dict, str | None]:
    """Tiny YouTube Data API GET helper (returns (json, error_message))."""
    if not YOUTUBE_API_KEY:
        return {}, "missing_api_key"
    try:
        params = dict(params or {})
        params["key"] = YOUTUBE_API_KEY
        r = requests.get(f"https://www.googleapis.com/youtube/v3/{path}", params=params, timeout=timeout)
        r.raise_for_status()
        return (r.json() or {}), None
    except Exception as e:
        print("[yt] http error:", e)
        return {}, str(e)

def _yt_review_summary(slug: str, brand: str, model: str, intent: dict) -> str:
    """
    Build one crisp reviewer sentence from cached/live YT bullets.
    Returns '' if nothing useful.
    """
    try:
        pros, cons = _load_youtube_signals(slug, brand, model)
    except Exception:
        pros, cons = [], []

    pros = [p for p in (pros or []) if p.strip()]
    cons = [c for c in (cons or []) if c.strip()]
    if not pros and not cons:
        return ""

    # Prefer 1–2 pros + 1 con as a single sentence
    raw = {
        "pros": pros[:2],
        "cons": cons[:1],
        "brand": brand,
        "model": model,
        "intent": intent,
    }

    if USE_LLM:
        try:
            prompt = (
                "Write ONE sentence with reviewer sentiment for shoppers. "
                "Use a neutral, confident tone (no hype), ~30–40 words. "
                "Blend the provided pros/cons. No lists, no colons.\n\n"
                f"Data: {json.dumps(raw, ensure_ascii=False)}\n"
                "Sentence:"
            )
            line = _ollama_text(prompt, temp=0.4) or ""
            line = re.sub(r"\s+", " ", line).strip()
            if line and 10 <= len(line.split()) <= 35:
                return line
        except Exception:
            pass

    # Deterministic fallback
    pros_part = ", ".join(pros[:2]) if pros else ""
    cons_part = cons[0] if cons else ""
    if pros_part and cons_part:
        return f"Reviewers praise {pros_part}, but note {cons_part}."
    if pros_part:
        return f"Reviewers praise {pros_part}."
    if cons_part:
        return f"Reviewers often note {cons_part}."
    return ""

def _yt_signals_pair(res) -> tuple[list[str], list[str]]:
    """
    Normalize any return shape into (pros, cons) lists.
    Accepts (pros, cons), [pros, cons, ...], dicts, or None.
    """
    try:
        if isinstance(res, (tuple, list)) and len(res) >= 2:
            return list(res[0] or []), list(res[1] or [])
        if isinstance(res, dict):
            return list(res.get("pros") or []), list(res.get("cons") or [])
    except Exception:
        pass
    return [], []



def _yt_search_reviews(brand: str, model: str, max_results: int = 6) -> list[dict]:
    """Search YouTube for '<brand> <model> review' (recent & relevant)."""
    q = f"{brand} {model} review"
    data, err = _yt_http("search", {
        "part": "snippet",
        "q": q,
        "maxResults": max(1, min(10, int(max_results))),
        "type": "video",
        "order": "relevance",
        "safeSearch": "none",
        "regionCode": "US",
    })
    if err:
        return []
    out = []
    for item in (data.get("items") or []):
        vid = (((item.get("id") or {}).get("videoId")) or "").strip()
        title = ((item.get("snippet") or {}).get("title") or "").strip()
        if vid:
            out.append({"videoId": vid, "title": title})
    return out


def _yt_fetch_transcript(video_id: str) -> str:
    """
    Best-effort transcript. Uses youtube-transcript-api if available; otherwise
    falls back to the video title/description (via videos.list).
    """
    # 1) Try youtube-transcript-api (if installed)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
        try:
            parts = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
            text = " ".join([p.get("text", "") for p in parts if p.get("text")])
            if text.strip():
                return text
        except (TranscriptsDisabled, NoTranscriptFound):
            pass
        except Exception:
            pass
    except Exception:
        pass

    # 2) Fallback: title + description
    meta, err = _yt_http("videos", {"part": "snippet", "id": video_id}, timeout=10)
    if not err:
        items = meta.get("items") or []
        if items:
            sn = (items[0] or {}).get("snippet") or {}
            title = (sn.get("title") or "").strip()
            desc = (sn.get("description") or "").strip()
            return f"{title}\n{desc}"
    return ""


def _dedupe_bullets(lst: list[str], limit: int) -> list[str]:
    """
    Case-insensitive semantic dedupe:
    - lowercases + strips
    - normalizes common price synonyms (expensive/pricey)
    - removes near-duplicates ("very expensive" -> "expensive")
    """
    if not lst:
        return []
    norm_map = {
        "pricey": "expensive",
        "very expensive": "expensive",
        "too expensive": "expensive",
        "high price": "expensive",
        "overpriced": "expensive",
        "cheap": "affordable",
        "very cheap": "affordable",
    }
    seen = set()
    out = []
    for raw in lst:
        s = (raw or "").strip()
        low = s.lower()
        low = norm_map.get(low, low)
        # strip adverbs like "very ", "quite " for dedupe purposes
        low = re.sub(r"^(very|quite|really)\s+", "", low)
        # collapse whitespace
        low = re.sub(r"\s+", " ", low)
        if low and low not in seen:
            seen.add(low)
            out.append(s)
        if len(out) >= limit:
            break
    return out


def _extract_pros_cons_from_text(text: str, intent: dict) -> tuple[list[str], list[str]]:
    """
    Turn messy transcript text into concise, human-friendly pros/cons.
    Returns (pros, cons). Uses LLM first; falls back to lightweight heuristics.
    """
    text = (text or "").strip()
    if not text:
        return [], []

    if USE_LLM:
        try:
            prompt = (
                "From the review text below, extract concise **pros** (3–6) and **cons** (2–5). "
                "Return STRICT JSON with keys 'pros' and 'cons'.\n"
                "- Make each bullet specific (6–12 words), not generic.\n"
                "- Deduplicate and avoid saying the same thing twice.\n"
                "- Keep a plain, helpful tone.\n\n"
                f"User intent (for relevance): {json.dumps(intent, ensure_ascii=False)}\n\n"
                f"Review text:\n{text}\n\nJSON:"
            )
            jtxt = chat_complete([{"role": "user", "content": prompt}], max_tokens=280, temperature=0.2)
            if jtxt:
                import re as _re, json as _json
                j = None
                try:
                    j = _json.loads(jtxt)
                except _json.JSONDecodeError:
                    m = _re.search(r"\{.*\}", jtxt, _re.S)
                    if m:
                        j = _json.loads(m.group(0))
                if isinstance(j, dict):
                    pros = [str(x).strip() for x in (j.get("pros") or []) if str(x).strip()][:6]
                    cons = [str(x).strip() for x in (j.get("cons") or []) if str(x).strip()][:5]
                    return pros, cons
        except Exception as e:
            print("[yt] LLM extraction failed:", e)

    # --- Heuristic fallback (kept a bit richer) ---
    t = text.lower()
    pros, cons = [], []

    def add(lst, s, limit):
        s = s.strip()
        if s and s.lower() not in {x.lower() for x in lst} and len(lst) < limit:
            lst.append(s)

    if any(k in t for k in ["battery", "endurance", "screen-on time"]):
        add(pros, "Battery comfortably lasts a full day", 6)
    if any(k in t for k in ["display", "screen", "brightness"]):
        add(pros, "Bright, sharp display that’s easy to read", 6)
    if any(k in t for k in ["camera", "photo", "video", "hdr"]):
        add(pros, "Cameras capture detailed, pleasing photos", 6)
    if any(k in t for k in ["performance", "chip", "snapdragon", "exynos", "dimensity"]):
        add(pros, "Smooth performance across apps and games", 6)
    if "charging" in t:
        add(pros, "Charge speeds feel quick in daily use", 6)

    if any(k in t for k in ["price", "expensive"]):
        add(cons, "Price feels high versus close rivals", 5)
    if any(k in t for k in ["heavy", "weight"]):
        add(cons, "A bit heavy in hand or pocket", 5)
    if "large" in t and "display" in t:
        add(cons, "Large size won’t suit small-phone fans", 5)

    return pros, cons




def _append_review_row(slug: str, pros: list[str], cons: list[str], sources: list[str] | None = None) -> None:
    """Append/update one row in data/processed/reviews.csv safely."""
    try:
        rows = []
        if _REVIEWS_CSV.exists():
            with _REVIEWS_CSV.open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

        found = False
        for r in rows:
            if (r.get("slug") or "") == slug:
                r["pros"] = "|".join(pros or [])
                r["cons"] = "|".join(cons or [])
                r["sources"] = "|".join(sources or [])
                r["ts"] = datetime.utcnow().isoformat()
                found = True
                break

        if not found:
            rows.append({
                "slug": slug,
                "pros": "|".join(pros or []),
                "cons": "|".join(cons or []),
                "sources": "|".join(sources or []),
                "ts": datetime.utcnow().isoformat(),
            })

        with _REVIEWS_CSV.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["slug", "pros", "cons", "sources", "ts"])
            w.writeheader()
            for r in rows:
                w.writerow({
                    "slug": r.get("slug",""),
                    "pros": r.get("pros",""),
                    "cons": r.get("cons",""),
                    "sources": r.get("sources",""),
                    "ts": r.get("ts",""),
                })
    except Exception as e:
        print("[yt] cache write failed:", e)



def _live_youtube_signals(slug: str, brand: str, model: str) -> tuple[list[str], list[str]]:
    """
    Query YouTube for this model, pull a few transcripts, extract pros/cons,
    dedupe + trim. Returns (pros, cons) ONLY.
    """
    if not YOUTUBE_API_KEY:
        return [], []

    try:
        vids = _yt_search_reviews(brand, model, max_results=5)
        texts = []
        for v in vids[:3]:
            vid = v.get("videoId")
            if not vid:
                continue
            txt = _yt_fetch_transcript(vid)
            if txt:
                texts.append(txt)
            _time.sleep(0.2)

        joined = "\n\n".join(texts).strip()
        if not joined:
            joined = "\n".join([x.get("title", "") for x in vids])

        pros, cons = _extract_pros_cons_from_text(joined, intent=SESSIONS.get(slug, {}).get("intent", {}))

        # dedupe & trim
        def _clean(lst, limit):
            out, seen = [], set()
            for x in (lst or []):
                s = (x or "").strip()
                if not s:
                    continue
                key = s.lower()
                if key not in seen:
                    seen.add(key)
                    out.append(s)
                if len(out) >= limit:
                    break
            return out

        return _clean(pros, 6), _clean(cons, 5)

    except Exception as e:
        print("[yt] live signals failed:", e)
        return [], []


def _load_youtube_signals(slug: str, brand: str | None = None, model: str | None = None) -> tuple[list[str], list[str]]:
    """
    1) Try local cache (data/processed/reviews.csv).
    2) If missing and API key present, fetch live, cache, and return.
    Always returns (pros, cons).
    """
    # 1) Cache
    if _REVIEWS_CSV.exists():
        try:
            with _REVIEWS_CSV.open(encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    if (row.get("slug") or "") == slug:
                        pros = (row.get("pros") or "").split("|") if row.get("pros") else []
                        cons = (row.get("cons") or "").split("|") if row.get("cons") else []
                        if pros or cons:
                            return pros, cons
        except Exception as e:
            print("[yt] cache read failed:", e)

    # 2) Live fetch if possible
    if YOUTUBE_API_KEY and brand and model:
        pros, cons = _live_youtube_signals(slug, brand, model)
        if pros or cons:
            _append_review_row(slug, pros, cons)  # sources optional now
            return pros, cons

    return [], []


# ------------------ end YouTube live block ------------------

# =========================
# Config
# =========================

USE_OLLAMA = os.getenv("USE_OLLAMA", "1") == "1"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")  # good balance offline

# =========================
# FastAPI
# =========================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or your explicit list if you prefer
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# near other imports
from fastapi import HTTPException, Query
from gsma_scraper import fetch_brand_since, ScrapeError
import pandas as pd, pathlib, csv, os

@app.get("/import/gsma/ping")
def gsma_ping():
    return {"ok": True}

@app.get("/dxo/test")
def dxo_test(brand: str, model: str):
    if not USE_DXOMARK_LIVE:
        return {"ok": False, "reason": "USE_DXOMARK_LIVE=0"}
    s = fetch_dxomark_camera_score(brand, model)
    return {"ok": True, "brand": brand, "model": model, "camera_score": s}

# optional: nudge rank score when DXO exists
def _dxo_bonus(brand: str, model: str) -> float:
    if not USE_DXOMARK_LIVE:
        return 0.0
    try:
        s = fetch_dxomark_camera_score(brand, model)
        if s:
            # scale 100–160 → 0–2.0 bonus
            return max(0.0, (s - 100) / 30.0)
    except Exception as e:
        print("[dxo] failed:", e)
    return 0.0

# --- simple probe endpoint ---
@app.get("/reddit/test")
def reddit_test(brand: str, model: str):
    if not USE_REDDIT_LIVE:
        return {"ok": False, "reason": "USE_REDDIT_LIVE=0"}
    pros, cons, sources = summarize_reddit(brand, model, max_posts=5)
    return {"ok": True, "brand": brand, "model": model, "pros": pros, "cons": cons, "sources": sources}

# --- helper to fetch reddit bullets in your pick-build path ---
def _reddit_signals(slug: str, brand: str, model: str) -> tuple[list[str], list[str]]:
    if not USE_REDDIT_LIVE:
        return [], []
    try:
        pros, cons, _src = summarize_reddit(brand, model, max_posts=4)
        return pros[:4], cons[:3]
    except Exception as e:
        print("[reddit] failed:", e)
        return [], []

@app.get("/import/gsma/brand")
def import_gsma_brand(
    brand: str = Query(..., description="Brand name, e.g., Apple"),
    min_year: int = Query(2023, ge=2008, le=2100),
):
    # guard if you keep a flag
    if not os.getenv("ALLOW_SCRAPERS", "0") == "1":
        raise HTTPException(status_code=403, detail="Scraping disabled (set ALLOW_SCRAPERS=1).")
    # lazy import so module load never fails
    from gsma_scraper import fetch_brand_since
    rows = fetch_brand_since(brand=brand, min_year=min_year)

    try:
        rows = fetch_brand_since(brand=brand, min_year=min_year)
    except ScrapeError as e:
        # 502 so Swagger shows message, not bare 500
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"unexpected: {e.__class__.__name__}")

    # write/append to a normalized CSV
    out_path = pathlib.Path("data/processed/phones_gsma.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    if df.empty:
        return {"ok": True, "imported": 0}

    # add Slug + PriceUSD placeholder so your existing code can load it
    # add Slug + PriceEUR placeholder (EUR system)
    def _slugify(s):
        import re
        s = (s or "").strip().lower()
        s = re.sub(r"[^a-z0-9]+", "-", s)
        return s.strip("-")
    df["Slug"] = (df["Brand"].astype(str) + "-" + df["Model"].astype(str)).map(_slugify)
    df["PriceEUR"] = None  # placeholder; we run EUR fallbacks later


    if out_path.exists():
        old = pd.read_csv(out_path)
        all_ = pd.concat([old, df], ignore_index=True)
        all_.drop_duplicates(subset=["Slug"], keep="last", inplace=True)
        all_.to_csv(out_path, index=False)
    else:
        df.to_csv(out_path, index=False)

    return {"ok": True, "imported": int(df.shape[0]), "file": str(out_path)}


@app.get("/import/gsma/probe")
def import_gsma_probe(brand: str):
    try:
        from gsma_scraper import find_brand_url
        url = find_brand_url(brand)
        return {"ok": True, "brand": brand, "brand_url": url}
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "trace": traceback.format_exc(limit=4)}

@app.post("/import/gsma/batch")
def import_gsma_batch(min_year: int = 2023):
    brands = [
        "Apple","Samsung","Google","OnePlus","Xiaomi","Sony",
        "Motorola","Nothing","Asus","Oppo","Vivo","Realme","Honor"
    ]
    total = 0
    for b in brands:
        try:
            got = fetch_brand_since(b, min_year=min_year)
            total += len(got)
        except Exception as e:
            print("[gsma] batch brand failed:", b, e)
    return {"ok": True, "brands": len(brands), "added_or_updated": total}

@app.get("/")
def root():
    return {"ok": True, "docs": "/docs", "health": "/healthz"}
# =========================
# Session store
# =========================
SESSIONS: Dict[str, Dict[str, Any]] = {}

# =========================
# Data loading (EUR only)
# =========================
_DF_CACHE: Optional[pd.DataFrame] = None
_PRICES_CACHE: Optional[pd.DataFrame] = None # New global cache for prices

EXPECTED_COLS = [
    "ID","Brand","Model","Slug","ReleaseYear","PriceEUR","DisplayInches",
    "Battery_mAh","RAM_GB","Storage_GB","MainCameraMP","OS","Weight_g",
    "NotableFeatures","SourceFiles"
]

def _price_fallback_eur(row: pd.Series) -> Optional[float]:
    """Heuristic EUR fallback if dataset price missing."""
    p = row.get("PriceEUR")
    if isinstance(p, (int, float)) and p and p > 20:
        return float(p)
    year = int(row.get("ReleaseYear") or 0)
    ram = float(row.get("RAM_GB") or 0)
    storage = float(row.get("Storage_GB") or 0)
    brand = (row.get("Brand") or "").lower()
    base = 230.0  # base in EUR
    if year >= 2024: base += 140
    elif year >= 2022: base += 75
    base += (ram * 17.0) + (storage/128.0)*45.0
    if brand in ["apple","samsung","google","sony","asus","oneplus"]:
        base *= 1.18
    return round(max(base, 110.0), 2)

def load_df() -> pd.DataFrame:
    global _DF_CACHE, _PRICES_CACHE # Declare global
    if _DF_CACHE is not None:
        return _DF_CACHE
    if not os.path.exists(CSV_PATH):
        _DF_CACHE = pd.DataFrame(columns=EXPECTED_COLS)
        return _DF_CACHE

    df = pd.read_csv(CSV_PATH, low_memory=False)

    # Ensure required columns exist
    for c in EXPECTED_COLS:
        if c not in df.columns:
            df[c] = None

    # ONE-TIME legacy conversion: if a CSV still has PriceUSD and no PriceEUR, convert then drop USD
    if "PriceEUR" not in df.columns and "PriceUSD" in df.columns:
        df["PriceEUR"] = pd.to_numeric(df["PriceUSD"], errors="coerce") * (FX_EUR_PER_USD or 0)
    if "PriceUSD" in df.columns:
        # we won't use USD anywhere; drop to avoid accidental use
        try:
            df.drop(columns=["PriceUSD"], inplace=True)
        except Exception:
            pass

    # numeric coercion
    to_num = {
        "ReleaseYear":"Int64", "PriceEUR":"float", "DisplayInches":"float",
        "Battery_mAh":"Int64", "RAM_GB":"float", "Storage_GB":"float",
        "MainCameraMP":"float", "Weight_g":"float"
    }
    for c, _ in to_num.items():
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # realistic price fallback if missing (EUR)
    if "PriceEUR" in df.columns:
        df["PriceEUR"] = df["PriceEUR"].where((df["PriceEUR"] > 20) & df["PriceEUR"].notna())
        df["PriceEUR"] = df.apply(_price_fallback_eur, axis=1)

    # strip strings
    for c in ["Brand","Model","OS","NotableFeatures","Slug"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()

    _DF_CACHE = df
    _PRICES_CACHE = load_prices_cache() # Load prices cache here
    return _DF_CACHE

def safe_df() -> pd.DataFrame:
    return load_df().copy()

# --- Reddit OAuth search (drop-in) -------------------------------------------
import base64, time as _t

_REDDIT_TOKEN = {"value": None, "exp": 0}

def _reddit_token() -> str | None:
    cid = os.getenv("REDDIT_CLIENT_ID", "")
    sec = os.getenv("REDDIT_SECRET", "")
    ua  = os.getenv("REDDIT_USER_AGENT", "phonefinder/1.0")
    if not (cid and sec): 
        return None
    if _t.time() < _REDDIT_TOKEN["exp"] - 30 and _REDDIT_TOKEN["value"]:
        return _REDDIT_TOKEN["value"]
    try:
        auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
        r = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            data={"grant_type":"client_credentials"},
            headers={"Authorization": f"Basic {auth}", "User-Agent": ua},
            timeout=12,
        )
        r.raise_for_status()
        j = r.json()
        token = j.get("access_token")
        if token:
            _REDDIT_TOKEN.update({"value": token, "exp": _t.time() + int(j.get("expires_in", 3600))})
            return token
    except Exception as e:
        print("[reddit] token failed:", e)
    return None

def _reddit_search(q: str, limit: int = 4) -> list[dict]:
    token = _reddit_token()
    if not token:
        raise RuntimeError("missing_reddit_oauth")
    ua = os.getenv("REDDIT_USER_AGENT", "phonefinder/1.0")
    r = requests.get(
        "https://oauth.reddit.com/search",
        params={"q": q, "sort": "relevance", "t": "year", "type": "link", "limit": max(1, min(10, limit))},
        headers={"Authorization": f"Bearer {token}", "User-Agent": ua},
        timeout=12,
    )
    r.raise_for_status()
    j = r.json()
    out = []
    for ch in (j.get("data", {}).get("children") or []):
        d = ch.get("data") or {}
        out.append({
            "title": d.get("title"),
            "url": ("https://www.reddit.com" + d.get("permalink")) if d.get("permalink") else d.get("url"),
            "selftext": d.get("selftext") or "",
        })
    return out

def reddit_signals_for_phone(brand: str, model: str, max_posts: int = 4) -> tuple[list[str], list[str]]:
    """Return (pros, cons) extracted from top reddit posts about this phone."""
    try:
        q = f"\"{brand} {model}\" review OR battery OR camera OR heating OR lag OR bug"
        posts = _reddit_search(q, limit=max_posts)
    except Exception as e:
        print("[reddit] failed:", e); return [], []
    # very light heuristics; your LLM extractor can be reused if you want
    text = "\n\n".join(
        [f"{p.get('title','')}\n{p.get('selftext','')}" for p in posts]
    )[:15000]
    # reuse your existing extractor to stay consistent
    pros, cons = _extract_pros_cons_from_text(text, intent={})
    return _dedupe_bullets(pros, 5), _dedupe_bullets(cons, 4)
# --- end reddit block --------------------------------------------------------


# =========================
# Models
# =========================
class ChatStartResp(BaseModel):
    session_id: str
    message: str
    ui: dict

class ChatMessageReq(BaseModel):
    session_id: str
    message: str

class ChatPatchReq(BaseModel):
    session_id: str
    patch: dict  # partial intent from UI controls (no NLP)

class ChatMessageResp(BaseModel):
    session_id: str
    intent: dict
    ask: Optional[str] = None
    picks: Optional[List[dict]] = None
    count: int = 0
    ui: Optional[dict] = None  # control hints

# =========================
# Intent helpers
# =========================
DEFAULT_INTENT: Dict[str, Any] = {
    "budget": None,
    "os": None,  # "Android" | "iOS"
    "prefer_small": None,  # True/False
    "prefer_large": None,  # True/False
    "min_battery": None,
    "min_ram": None,
    "min_storage": None,
    "min_camera": None,
    "brands": [],
    "avoid_brands": [],
    "must_have": [],
    "min_year": 2018,
    "max_year": None,
    "camera_priority": None,  # True/False
}

SLOTS = [
    ("budget", "What’s your budget?"),
    ("os", "Android or iOS — or no preference?"),
    ("prefer_small", "Prefer compact (~6.1\") or larger screens (6.7\"+)?"),
    ("min_battery", "Do you care about battery life? (we’ll aim ≥ 5000 mAh)"),
    ("must_have", "Any must-haves: 5G, wireless charging, IP68, eSIM?"),
    ("brands", "Any brands to prefer or avoid?"),
    ("min_ram", "Minimum RAM? (we’ll suggest if unsure)"),
    ("min_storage", "Minimum storage? (e.g., 128 GB)"),
    ("camera_priority", "Are good photos a priority? (yes/no)"),
]

NON_TECH_HINTS = {
    "budget": {"type":"slider", "min":100, "max":2000, "step":50, "unit":"€"},
    "os": {"type":"segmented", "options":["No preference","Android","iOS"]},
    "prefer_small": {"type":"segmented", "options":["No preference","Compact","Larger"]},
    "min_battery": {"type":"segmented", "options":["No preference","Long battery"]},
    "must_have": {"type":"chips", "options":["5G","Wireless charging","IP68","eSIM"]},
    "brands": {"type":"chips", "options":["Apple","Samsung","Google","OnePlus","Xiaomi","Sony","Motorola","Nothing","Asus","Oppo","Vivo","Realme","Honor"]},
    "min_ram": {"type":"segmented", "options":["No preference","6 GB","8 GB","12 GB"]},
    "min_storage": {"type":"segmented", "options":["No preference","128 GB","256 GB","512 GB"]},
    "camera_priority": {"type":"segmented", "options":["No preference","Yes","No"]},
}

SKIP_PAT = re.compile(r"\b(skip|none|no preference|idk|don'?t know)\b", re.I)

def wants_to_skip(txt: str) -> bool:
    return bool(SKIP_PAT.search(txt or ""))

def _json_safe_num(x, cast):
    try:
        v = cast(x)
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v
    except Exception:
        return None

def _clean_pick(p: dict) -> dict:
    q = dict(p or {})
    for k, caster in [
        ("ReleaseYear", int), ("PriceEUR", float), ("DisplayInches", float),
        ("Battery_mAh", int), ("RAM_GB", float), ("Storage_GB", float),
        ("MainCameraMP", float), ("Weight_g", float),
    ]:
        if k in q:
            q[k] = _json_safe_num(q[k], caster)
    for k in ["Brand","Model","OS","NotableFeatures","ImageURL","ImageLocal","BrandLogo"]:
        if k in q:
            q[k] = None if q[k] is None else str(q[k])
    for k in ["Pros","Cons"]:
        if k in q and not isinstance(q[k], list):
            q[k] = []
        if isinstance(q.get(k), list):
            q[k] = [str(x) for x in q[k] if x is not None][:10]
    if isinstance(q.get("LiveOffer"), dict):
        offer = q["LiveOffer"]
        q["LiveOffer"] = {
            "retailer": str(offer.get("retailer") or ""),
            "price": _json_safe_num(offer.get("price"), float),
            "currency": str(offer.get("currency") or "EUR"),   # <— EUR default
            "url": str(offer.get("url") or ""),
            "in_stock": bool(offer.get("in_stock")),
        }
    return q


def _strict_budget_df(d: pd.DataFrame, budget) -> pd.DataFrame:
    """Return only rows with a known positive EUR price <= budget. No-op when budget is None."""
    if d is None or d.empty or budget in (None, "", 0):
        return d
    price = pd.to_numeric(d["PriceEUR"], errors="coerce")
    return d.loc[(~price.isna()) & (price > 0) & (price <= float(budget))].copy()

def _none_if_nan(x):
    try:
        import math
        return None if (x is None or (isinstance(x, float) and math.isnan(x))) else x
    except Exception:
        return x

def _strict_budget_picks(picks: list[dict], budget) -> list[dict]:
    """Keep only picks priced <= budget (when known), based on EUR."""
    if not picks or budget in (None, "", 0):
        return picks or []
    b = float(budget)
    out = []
    for p in picks:
        try:
            # prefer live offer price; else PriceEUR field
            price = float((p.get("LiveOffer") or {}).get("price") or p.get("PriceEUR") or 0)
        except Exception:
            price = 0
        if price and price <= b:
            out.append(p)
    return out

def _blurb_for_row(intent: dict, row: pd.Series) -> Optional[str]:
    """
    Try LLM blurb (chat_complete) → local _compose_blurb → llm_blurb → None.
    If YouTube review pros exist for this slug, append a short sentence:
    "Reviewers highlight …"
    """
    brand = str(row.get("Brand") or "").strip()
    model = str(row.get("Model") or "").strip()
    slug = row.get("Slug")
    try:
        is_nan_slug = pd.isna(slug)
    except Exception:
        is_nan_slug = False
    if not slug or is_nan_slug or str(slug).lower() == "nan":
        slug = _slugify(f"{brand}-{model}")

    base = None

    # LLM-first (Groq/OpenAI via chat_complete)
    try:
        if USE_LLM:
            facts = {
                "Brand": brand,
                "Model": model,
                "OS": str(row.get("OS") or "").strip(),
                "ReleaseYear": int(row.get("ReleaseYear") or 0),
                "PriceEUR": row.get("PriceEUR"),
                "DisplayInches": row.get("DisplayInches"),
                "Battery_mAh": row.get("Battery_mAh"),
                "RAM_GB": row.get("RAM_GB"),
                "Storage_GB": row.get("Storage_GB"),
                "MainCameraMP": row.get("MainCameraMP"),
            }
            msgs = blurb_messages(intent, facts)
            txt = chat_complete(msgs, max_tokens=140, temperature=0.4)
            if txt:
                txt = re.sub(r"\s+", " ", txt).strip()
                if txt:
                    base = txt[:500]
    except Exception as _e:
        print("[LLM blurb] fallback:", _e)

    # Local helper fallback
    if not base:
        try:
            base = _compose_blurb(intent, row)
        except Exception:
            base = None

    if not base:
        try:
            base = llm_blurb(intent, row)
        except Exception:
            base = None

    # Try to enrich with YouTube highlights (cached or live)
    try:
        yt_pros, _ = _load_youtube_signals(slug, brand, model)
        yt_pros = _dedupe_bullets(yt_pros, 3)
        if yt_pros:
            joined = ", ".join(yt_pros[:2]) if len(yt_pros) >= 2 else yt_pros[0]
            extra = f" Reviewers highlight {joined.lower()}."
            base = (base or "").strip()
            base = (base + extra) if base else ("Reviewers highlight " + joined.lower() + ".")
    except Exception as _e:
        pass

    return base




import csv, pathlib

def best_offer_for_slug(slug: str) -> dict | None:
    path = pathlib.Path("data/processed/offers.csv")
    if not path.exists():
        return None
    best = None
    with path.open(encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            if row["slug"] == slug and row.get("price"):
                try:
                    p = float(row["price"])
                except: 
                    continue
                if best is None or p < best["price"]:
                    best = {
                        "retailer": row["retailer"],
                        "price": p,
                        "currency": row.get("currency","USD"),
                        "url": row["url"],
                        "in_stock": row.get("in_stock") in ("True","true","1"),
                    }
    return best

from gsma_scraper import fetch_specs_live  # <-- add at top of file

def _direct_results_response(session_id: str, intent: dict, skipped: set | None = None) -> ChatMessageResp:
    """Build results strictly from current intent with budget hard-guard and a personalized blurb."""

    skipped = skipped or set()

    # 1) strict filter (your filter_df_by_intent already respects budget)
    d = filter_df_by_intent(safe_df(), intent)
    d = _strict_budget_df(d, intent.get("budget"))

    # 2) if empty and OS set, keep OS only (but still apply budget!)
    if d.empty and intent.get("os"):
        os_only = {"os": intent["os"], "min_year": intent.get("min_year") or 2018}
        d = filter_df_by_intent(safe_df(), os_only)
        d = _strict_budget_df(d, intent.get("budget"))

    # 3) final fallback: newest → cheapest, BUT still apply budget guard
    if d.empty:
        d = safe_df().sort_values(["ReleaseYear", "PriceEUR"], ascending=[False, True], na_position="last")
        d = _strict_budget_df(d, intent.get("budget"))

    count = int(len(d))

    # rank + build (cap to 3)
    ranked = rank_df(d, intent)
    picks = _build_picks_from_df(ranked.head(30), intent)
    picks = _strict_budget_picks(picks, intent.get("budget"))[:3]

    # --- LIVE GSMA SPEC ENRICHMENT ---
    for p in picks:
        try:
            # Only fetch if missing or placeholder values
            if not p.get("DisplayInches") or p.get("DisplayInches") < 3:
                brand = p.get("Brand") or p.get("brand")
                model = p.get("Model") or p.get("model")
                if brand and model:
                    live_specs = fetch_specs_live(brand, model)
                    if live_specs:
                        print(f"[gsma-live] enriched {brand} {model} with {len(live_specs)} fields")
                        p.update({k: v for k, v in live_specs.items() if v})
        except Exception as e:
            print(f"[gsma-live] failed for {p.get('Brand')} {p.get('Model')}: {e}")
    # ----------------------------------

    # blurb: prefer per-pick blurb for the featured card
    ask = None
    if picks:
        ask = (picks[0] or {}).get("Blurb") or None
    if not ask:
        try:
            if not ranked.empty:
                ask = _blurb_for_row(intent, ranked.iloc[0]) or None
        except Exception:
            ask = None
    if not ask and picks:
        top = picks[0]
        ask = f"I’d start with {top['Brand']} {top['Model']} — strong match for what you asked."


    # save
    SESSIONS[session_id] = {"intent": intent, "ask_key": None, "skipped": skipped}

    return ChatMessageResp(
        session_id=session_id,
        intent=intent,
        ask=ask,
        picks=[_clean_pick(p) for p in (picks or []) if isinstance(p, dict)],
        count=count,
        ui=ui_config(),
    )


def live_count(intent: Dict[str, Any]) -> int:
    return int(len(filter_df_by_intent(safe_df(), intent, strict_budget=False)))

def _sanitize_conflicts(intent: dict) -> dict:
    """Resolve self-contradictory filters so we don't return 0 on technicalities."""
    out = dict(intent or {})
    osv = (out.get("os") or "").strip().lower()
    brands = [b for b in (out.get("brands") or []) if b]

    # If OS is Android, Apple brand makes the set impossible. Drop Apple from likes.
    if osv.startswith("a") and brands:
        brands = [b for b in brands if b.strip().lower() != "apple"]
        out["brands"] = brands

    # If OS is iOS, and likes list contains no Apple, relax OS (let data breathe).
    if (osv.startswith("i")) and brands:
        if not any(b.strip().lower() == "apple" for b in brands):
            out["os"] = None  # iOS-only with non-Apple brands can't match → relax OS

    # If avoid_brands includes everything liked, drop avoid (be kind)
    avoids = [b for b in (out.get("avoid_brands") or []) if b]
    if brands and avoids and all(b in avoids for b in brands):
        out["avoid_brands"] = []

    return out


def candidates_multi(intent: dict) -> tuple[pd.DataFrame, dict, str]:
    df_all = safe_df()
    i0 = dict(intent)

    def filt(i: dict, strict: bool) -> pd.DataFrame:
        return filter_df_by_intent(df_all, i, strict_budget=strict)

    # 1) Strict budget
    d = filt(i0, True)
    if len(d) >= 3:
        return d, i0, "strict budget"

    # 2) Soft budget (allow unknown price)
    d = filt(i0, False)
    if len(d) >= 3:
        return d, i0, "soft budget"

    # 3) Drop must-have
    if i0.get("must_have"):
        i = dict(i0); i["must_have"] = []
        d = filt(i, False)
        if len(d) >= 3:
            return d, i, "dropped must-have"

    # 4) Relax budget +15% (strict)
    if i0.get("budget") is not None:
        try:
            i = dict(i0); i["budget"] = float(i0["budget"]) * 1.15
            d = filt(i, True)
            if len(d) >= 3:
                return d, i, "relaxed budget +15%"
        except Exception:
            pass

    # 5) Remove size constraint (soft)
    if i0.get("prefer_small") is True or i0.get("prefer_large") is True:
        i = dict(i0); i["prefer_small"] = None; i["prefer_large"] = None
        d = filt(i, False)
        if len(d) >= 3:
            return d, i, "removed size constraint"

    # 6) Relax minimums (soft)
    i = dict(i0)
    changed = False
    if i.get("min_battery") not in (None, 0):
        i["min_battery"] = max(0, int(i["min_battery"] * 0.9)); changed = True
    if i.get("min_ram") not in (None, 0):
        i["min_ram"] = max(1, int(i["min_ram"]) - 1); changed = True
    if i.get("min_storage") not in (None, 0):
        i["min_storage"] = max(16, int(i["min_storage"]) - 64); changed = True
    if changed:
        d = filt(i, False)
        if len(d) >= 3:
            return d, i, "relaxed minimums"

    # 7) Drop budget entirely (soft). Ranking will still penalize over budget.
    i = dict(i0); i.pop("budget", None)
    d = filt(i, False)
    if len(d) >= 3:
        return d, i, "ignored budget"

    # 8) Fallback newest then cheapest
    base = df_all.sort_values(["ReleaseYear","PriceEUR"], ascending=[False, True], na_position="last")
    return base.head(30), i0, "fallback newest"

def _merge_live_specs(row: pd.Series, brand: str, model: str) -> dict:
    """
    Merge GSMArena live specs into the row dict.
    We prefer live values when they exist; otherwise keep CSV value.
    """
    base = {
        "OS": row.get("OS"),
        "ReleaseYear": row.get("ReleaseYear"),
        "DisplayInches": row.get("DisplayInches"),
        "Battery_mAh": row.get("Battery_mAh"),
        "RAM_GB": row.get("RAM_GB"),
        "Storage_GB": row.get("Storage_GB"),
        "MainCameraMP": row.get("MainCameraMP"),
    }

    if not USE_GSMA_LIVE:
        return base

    live = {}
    try:
        live = fetch_specs_live(brand, model) or {}
    except ScrapeError as e:
        print(f"[gsma-live] {brand} {model}: {e}")
    except Exception as e:
        print(f"[gsma-live] unexpected for {brand} {model}: {e}")

    # prefer live when present and non-empty
    for k in list(base.keys()):
        v = live.get(k)
        if v not in (None, "", 0):
            base[k] = v

    return base
# --- Safe wrappers (place ABOVE _build_picks_from_df) -----------------

def _reddit_signals_for_phone(slug: str, brand: str, model: str) -> tuple[list[str], list[str]]:
    """
    Returns (pros, cons). If reddit_signals_for_phone(brand, model, max_posts)
    exists, call it; else return empty lists.
    """
    try:
        fn = globals().get("reddit_signals_for_phone")
        if callable(fn):
            return fn(brand, model, max_posts=4)
    except Exception as e:
        print("[reddit] failed:", e)
    return [], []

import os
from dxomark_live import fetch_dxomark_camera_rank

# optional shim so a missing reddit helper won’t crash:
try:
    from reddit_live import reddit_search_pros_cons as _reddit_search_pros_cons
except Exception:
    def _reddit_search_pros_cons(*_args, **_kwargs):  # (slug, brand, model) -> (pros, cons)
        return [], []

# at the top of the file if not already present

USE_IDEALO_LIVE = os.getenv("USE_IDEALO_LIVE", "0") == "1"
IDEALO_DOMAIN = os.getenv("IDEALO_DOMAIN", "idealo.de")  # change per region if you want

def _idealo_search_url(brand: str, model: str) -> str:
    from urllib.parse import quote_plus
    q = quote_plus(f"{brand} {model}")
    # generic search; user will click through; we only probe for lowPrice if allowed
    return f"https://www.{IDEALO_DOMAIN}/preisvergleich/MainSearchProductCategory.html?q={q}"

def fetch_price_with_llm(brand: str, model: str) -> tuple[float | None, str | None]:
    """
    Uses LLM to find the current price of a phone.
    Returns (price_eur, search_url) or (None, None) if not available.
    """
    if not USE_LLM:
        return None, None

    try:
        prompt = (
            f"What is the current approximate retail price of the {brand} {model} phone in EUR? "
            "Provide only the price as a number (e.g., 799.99). "
            "If you cannot find a price, respond with 'None'."
        )
        # Use the lighter Mixtral model as requested
        response_text = chat_complete([{"role": "user", "content": prompt}], model="mixtral-8x7b", max_tokens=20, temperature=0.1)

        if response_text and response_text.strip().lower() != "none":
            # Extract price from the response
            match = re.search(r"(\d[\d\.,]*)", response_text)
            if match:
                price_str = match.group(1).replace(",", ".")
                price = float(price_str)
                return price, f"https://www.google.com/search?q={quote_plus(f'{brand} {model} price')}"
    except Exception as e:
        print(f"[LLM price] failed for {brand} {model}: {e}")
    return None, None

@app.get("/llm/price_test_raw")
def llm_price_test_raw(brand: str, model: str):
    if not USE_LLM:
        return {"ok": False, "reason": "USE_LLM=0"}
    prompt = (
        f"What is the current approximate retail price of the {brand} {model} phone in EUR? "
        "Provide only the price as a number (e.g., 799.99). "
        "If you cannot find a price, respond with 'None'."
    )
    response_text = chat_complete([{"role": "user", "content": prompt}], model="mixtral-8x7b", max_tokens=20, temperature=0.1)
    return {"ok": True, "brand": brand, "model": model, "raw_response": response_text}


import os
from dxomark_live import cached_dxomark_rank
from urllib.parse import quote_plus
from backend.update_prices import load_prices_cache, save_prices_cache, fetch_price_via_llm_for_update

def _build_picks_from_df(d: pd.DataFrame, intent: dict) -> list[dict]:
    picks: list[dict] = []
    if d is None or d.empty:
        return picks

    # rank & de-dup
    try:
        ranked = rank_df(d, intent)
    except Exception as e:
        print("[rank_df] failed:", e)
        ranked = d
    try:
        ranked = unique_topn(ranked, 6)
    except Exception as e:
        print("[unique_topn] failed:", e)
        ranked = ranked.head(6)

    def _first_two(seq):
        try:
            if isinstance(seq, (list, tuple)):
                a = seq[0] if len(seq) > 0 else []
                b = seq[1] if len(seq) > 1 else []
                return (a or []), (b or [])
        except Exception:
            pass
        return [], []

    for _, row in ranked.iterrows():
        brand = (row.get("Brand") or "").strip()
        model = (row.get("Model") or "").strip()
        if not brand or not model:
            print("[build] skip row with missing brand/model:", row.to_dict())
            continue

        # --- Live specs merge (GSMA fallback) ---
        try:
            merged = _merge_live_specs(row, brand, model)
        except Exception as e:
            print("[merge_live_specs] failed:", e)
            merged = row

        # --- Slug + single image ---
        slug = row.get("Slug")
        try:
            is_nan_slug = pd.isna(slug)
        except Exception:
            is_nan_slug = False
        if not slug or is_nan_slug or str(slug).lower() == "nan":
            slug = _slugify(f"{brand}-{model}")

        try:
            image_url = fetch_phone_image_url(brand, model)
        except Exception as e:
            print("[image] fetch_phone_image_url failed:", e)
            image_url = None

        phone_local = (
            _public_url_if_exists(f"/phones/{slug}.jpg")
            or _public_url_if_exists(f"/phones/{slug}.png")
        )
        brand_key = brand.lower().replace(" ", "_")
        brand_logo = _public_url_if_exists(f"/brands/{brand_key}.png")

        # --- Gallery (Google Custom Search Engine) ---
        try:
            gallery_urls = fetch_images_from_google_cse(brand, model, limit=3)
        except Exception as _e:
            print(f"[gallery] Google CSE fetch failed: {_e}")
            gallery_urls = []

        # --- Pros / Cons (YT + LLM + Reddit) ---
        pros: list[str] = []
        cons: list[str] = []
        try:
            yt_pros, yt_cons = _yt_signals_pair(_load_youtube_signals(slug, brand, model))
            pros, cons = list(yt_pros or []), list(yt_cons or [])
            if not pros and not cons:
                llm_res = llm_pros_cons(intent, row)
                llm_pros, llm_cons = _first_two(llm_res)
                pros, cons = list(llm_pros or []), list(llm_cons or [])
        except Exception as e:
            print("[pros/cons-live] failed:", e)
            pros, cons = [], []
        try:
            r_pros, r_cons = _reddit_search_pros_cons(slug, brand, model)
            pros = (pros or []) + (r_pros or [])
            cons = (cons or []) + (r_cons or [])
        except Exception as e:
            print("[reddit merge] failed:", e)

        try:
            def _dedupe_cap(lst, cap):
                out, seen = [], set()
                for x in lst or []:
                    s = (x or "").strip()
                    k = s.lower()
                    if s and k not in seen:
                        seen.add(k); out.append(s)
                    if len(out) >= cap: break
                return out
            pros = _dedupe_cap(pros, 5)
            cons = _dedupe_cap(cons, 4)
            pros, cons = _filter_bullets_to_intent(pros, cons, intent, row)
        except Exception as e:
            print("[pros/cons-filter] failed:", e)

        def fnum(x, cast):
            try:
                return cast(x) if pd.notna(x) else None
            except Exception:
                return None

        # --- PRICE / OFFER (Cache -> LLM -> Amazon -> MSRP) ---
        price_src = "unknown"
        price_val = None
        price_url = None

        # 1) Price from cache
        global _PRICES_CACHE
        if _PRICES_CACHE is not None:
            cached_price = _PRICES_CACHE[_PRICES_CACHE["slug"] == slug]
            if not cached_price.empty:
                price_val = cached_price["price"].iloc[0]
                price_src = "cache"
                price_url = f"https://www.google.com/search?q={quote_plus(f'{brand} {model} price')}" # Use a generic search URL

        # 2) LLM price fetch (if not found in cache or cache is too old - handled by update_prices.py)
        if price_val is None and USE_LLM:
            try:
                p, llm_url = fetch_price_with_llm(brand, model)
                if p:
                    price_src, price_val, price_url = "llm_search", float(p), llm_url
                    # Optionally, update cache here if we want real-time cache updates
                    # For now, assume cache is updated by the separate script
            except Exception as _e:
                print("[price] LLM failed:", _e)

        # 3) Amazon live
        if price_val is None:
            try:
                amz = fetch_amazon_offer(brand, model)
                if amz and amz.get("price"):
                    price_src = "amazon"
                    price_val = float(amz.get("price"))
                    price_url = amz.get("url")
            except Exception as _e:
                print("[price] amazon failed:", _e)

        # 4) MSRP / CSV fallback
        if price_val is None:
            msrp_eur = fnum(row.get("PriceEUR"), float)
            if msrp_eur:
                price_src = "msrp"
                price_val = float(msrp_eur)
                price_url = None

        # --- Build item ---
        item = {
            "Brand": brand,
            "Model": model,
            "ReleaseYear": fnum(merged.get("ReleaseYear"), int) or 0,
            "PriceEUR": float(price_val) if price_val is not None else (fnum(row.get("PriceEUR"), float) or 0.0),
            "DisplayInches": fnum(merged.get("DisplayInches"), float),
            "Battery_mAh": fnum(merged.get("Battery_mAh"), int),
            "RAM_GB": fnum(merged.get("RAM_GB"), float),
            "Storage_GB": fnum(merged.get("Storage_GB"), float),
            "MainCameraMP": fnum(merged.get("MainCameraMP"), float),
            "OS": merged.get("OS"),
            "Weight_g": fnum(row.get("Weight_g"), float),
            "NotableFeatures": row.get("NotableFeatures"),
            "ImageLocal": phone_local,
            "ImageURL": image_url,
            "BrandLogo": brand_logo,
            "Gallery": gallery_urls,
            "Pros": pros or [],
            "Cons": cons or [],
        }

        # attach canonical offer struct + metadata if we have any price
        if price_val is not None:
            item["LiveOffer"] = {
                "retailer": price_src,
                "url": price_url,
                "price": float(price_val),
                "currency": "EUR",
                "in_stock": True,
            }
            item["PriceSource"] = price_src
            item["PriceLink"] = price_url

        # --- DXOMARK rank ---
        try:
            if os.getenv("USE_DXOMARK_LIVE", "1") == "1":
                rnk = cached_dxomark_rank(brand, model)
                if rnk is not None:
                    item["DxOMarkCameraRank"] = int(rnk)
        except Exception as e:
            print("[dxo] fetch failed:", e)

        # --- Explanations map ---
        try:
            item["Explain"] = attach_explanations(intent, row, item["Pros"], item["Cons"])
        except Exception as _e:
            print("[explain] failed:", _e)

        # --- Per-pick blurb (computed for all; UI only renders for featured) ---
        try:
            item["Blurb"] = _blurb_for_row(intent, row) or ""
        except Exception as e:
            print("[blurb] per-pick failed:", e)
            item["Blurb"] = ""

        picks.append(item)

    return picks


def _enrich_bullets_llm(intent: dict, brand: str, model: str,
                        pros: list[str], cons: list[str]) -> tuple[list[str], list[str]]:
    """
    Rewrite bullets to be specific, 6–12 words, and non-duplicative.
    If LLM is off/unavailable, returns inputs with light cleanup.
    """
    def _clean_list(lst: list[str], limit: int) -> list[str]:
        out, seen = [], set()
        for x in (lst or []):
            s = re.sub(r"\s+", " ", (x or "").strip())
            if not s:
                continue
            low = s.lower().rstrip(".")
            if low not in seen:
                seen.add(low)
                out.append(s[0].upper() + s[1:])
            if len(out) >= limit:
                break
        return out

    if not (USE_LLM and (pros or cons)):
        return _clean_list(pros, 6), _clean_list(cons, 5)

    try:
        prompt = (
            "Rewrite these bullets so each is specific, natural, and 6–12 words. "
            "Remove duplicates. Return STRICT JSON with keys 'pros' and 'cons'.\n\n"
            f"Phone: {brand} {model}\n"
            f"User intent: {json.dumps(intent, ensure_ascii=False)}\n"
            f"Pros: {json.dumps(pros, ensure_ascii=False)}\n"
            f"Cons: {json.dumps(cons, ensure_ascii=False)}\nJSON:"
        )
        jtxt = chat_complete([{"role": "user", "content": prompt}], max_tokens=220, temperature=0.2)
        if jtxt:
            import json as _json, re as _re
            j = None
            try:
                j = _json.loads(jtxt)
            except _json.JSONDecodeError:
                m = _re.search(r"\{.*\}", jtxt, _re.S)
                if m:
                    j = _json.loads(m.group(0))
            if isinstance(j, dict):
                return _clean_list(j.get("pros") or [], 6), _clean_list(j.get("cons") or [], 5)
    except Exception as e:
        print("[bullets] enrich failed:", e)

    return _clean_list(pros, 6), _clean_list(cons, 5)

@app.get("/gsma/test")
def gsma_test(brand: str, model: str):
    try:
        from gsma_scraper import fetch_specs_live
        specs = fetch_specs_live(brand, model)
        return {"ok": bool(specs), "brand": brand, "model": model, "specs": specs}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/yt/status")
def yt_status():
    import csv as _csv
    rows = 0
    if _REVIEWS_CSV.exists():
        with _REVIEWS_CSV.open(encoding="utf-8") as f:
            rows = sum(1 for _ in _csv.DictReader(f))
    return {
        "exists": _REVIEWS_CSV.exists(),
        "rows": rows,
        "live_enabled": bool(YOUTUBE_API_KEY),
    }
@app.get("/yt/debug")
def yt_debug(slug: str, brand: str, model: str):
    pros, cons = _live_youtube_signals(slug, brand, model)
    if pros or cons:
        _append_review_row(slug, pros, cons)
    return {"ok": bool(pros or cons), "pros": pros, "cons": cons}


@app.get("/config/status")
def config_status():
    from config import USE_LLM, PHONES_CSV
    return {
        "use_llm": bool(USE_LLM),
        "diag": bool(DIAG),
        "csv_path": PHONES_CSV,
        "df_rows": int(load_df().shape[0]) if load_df() is not None else 0
    }

def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")

def _public_exists(rel: str) -> bool:
    # Check typical dev paths for vite public assets
    for base in ["frontend/public", "public"]:
        if os.path.exists(os.path.join(base, rel.lstrip("/"))):
            return True
    return False

# === Begin: public path helpers ===
import os, re  # (ok if already imported above)

# Resolve frontend/public reliably (Windows-safe)
PUBLIC_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "frontend", "public")
)

def _public_url_if_exists(rel_path: str):
    """If file exists under frontend/public/<rel>, return '/<rel>' for the frontend to load; else None."""
    try:
        rel = (rel_path or "").replace("\\", "/").lstrip("/")      # 'brands/apple.png'
        fs_path = os.path.join(PUBLIC_DIR, *rel.split("/"))        # -> .../frontend/public/brands/apple.png
        if os.path.exists(fs_path):
            return f"/{rel}"                                       # frontend can load this directly
    except Exception:
        pass
    return None

def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")
# === End: public path helpers ===



STATIC_GLOSSARY = {
    "ram": "Memory for running apps. More RAM helps with smooth multitasking.",
    "storage": "Where your apps, photos and videos live. More storage means more room.",
    "mah": "Battery capacity. Higher mAh generally means longer battery life.",
    "ip68": "Water/dust resistance. Ok for rain and brief submersion.",
    "wireless charging": "Charge by placing on a pad. No cable in the port.",
    "fast charging": "Charges much quicker with a supported charger.",
    "esim": "Digital SIM. Activate service without a physical card.",
    "5g": "Faster mobile internet in supported areas.",
    "telephoto": "Camera lens for clearer zoom photos.",
    "ultrawide": "Camera lens that captures much wider scenes.",
    "120hz": "Smoother screen motion, helpful for scrolling and games."
}

def _labels_for_row(row: pd.Series) -> list[str]:
    labels = []
    try:
        ram = row.get("RAM_GB")
        if pd.notna(ram) and ram:
            labels.append(f"{int(ram) if float(ram).is_integer() else ram} GB RAM")
    except: pass
    try:
        st = row.get("Storage_GB")
        if pd.notna(st) and st:
            labels.append(f"{int(st) if float(st).is_integer() else st} GB storage")
    except: pass
    try:
        bat = row.get("Battery_mAh")
        if pd.notna(bat) and bat:
            labels.append(f"{int(bat)} mAh battery")
    except: pass
    feats = str(row.get("NotableFeatures") or "").lower()
    for key in ["ip68","wireless charging","fast charging","esim","5g","telephoto","ultrawide","120hz"]:
        if key in feats:
            labels.append(key.upper() if key in ["ip68","5g"] else key.title())
    return labels




# =========================
# LLM extraction (JSON)
# =========================
def _ollama_generate_json(prompt: str, options: dict | None = None) -> Optional[dict]:
    if not USE_OLLAMA:
        return None
    try:
        payload = {
            "model": OLLAMA_MODEL, "prompt": prompt,
            "stream": False, "format": "json"
        }
        if options: payload["options"] = options
        r = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=30)
        r.raise_for_status()
        raw = (r.json().get("response") or "{}").strip()
        return json.loads(raw)
    except Exception:
        return None

INTENT_SCHEMA = {
    "type":"object",
    "additionalProperties": False,
    "properties":{
        "budget":{"type":["number","null"]},
        "os":{"type":["string","null"]},
        "prefer_small":{"type":["boolean","null"]},
        "prefer_large":{"type":["boolean","null"]},
        "min_battery":{"type":["integer","null"]},
        "min_ram":{"type":["number","null"]},
        "min_storage":{"type":["number","null"]},
        "min_camera":{"type":["number","null"]},
        "brands":{"type":["array","null"], "items":{"type":"string"}},
        "avoid_brands":{"type":["array","null"], "items":{"type":"string"}},
        "must_have":{"type":["array","null"], "items":{"type":"string"}},
        "min_year":{"type":["integer","null"]},
        "max_year":{"type":["integer","null"]},
        "camera_priority":{"type":["boolean","null"]},
    }
}

def ai_extract_intent(text: str) -> dict:
    """Robust AI intent extraction with schema; returns {} on failure."""
    if not text:
        return {}
    sys = (
        "Extract phone-shopping intent from the user message. "
        "Return STRICT JSON matching this schema:\n"
        f"{json.dumps(INTENT_SCHEMA)}\n"
        "Rules:\n"
        "- Budget: numeric USD if 'under/<=/max €X' or a number appears.\n"
        "- OS: 'Android' or 'iOS' (capitalize) if preference stated, else null.\n"
        "- prefer_small true if compact/small (~6.1\"); prefer_large true if large/big (~6.7\"); else null.\n"
        "- must_have: subset of ['5G','wireless charging','IP68','eSIM'] if mentioned.\n"
        "- brands / avoid_brands from the message.\n"
        "- Do not invent values. Unstated -> null/empty."
    )
    j = _ollama_generate_json(sys + "\n\nUser: " + text + "\n\nJSON:", options={"temperature":0.1})
    if not isinstance(j, dict):
        return {}
    # clean up booleans
    if j.get("prefer_small") and j.get("prefer_large"):
        j["prefer_small"] = None; j["prefer_large"] = None
    # Normalize OS case
    if j.get("os"):
        s = str(j["os"]).lower()
        j["os"] = "iOS" if "ios" in s or "iphone" in s or "apple" in s else ("Android" if "android" in s else None)
    # Deduplicate arrays
    for k in ["brands","avoid_brands","must_have"]:
        vals = j.get(k) or []
        out, seen = [], set()
        for x in vals:
            s = (x or "").strip()
            if not s: continue
            sl = s.lower()
            if sl not in seen:
                seen.add(sl); out.append(s.title() if k != "must_have" else s.lower())
        j[k] = out
    return {k:v for k,v in j.items() if v not in (None, "", [], {})}

# Strong regex fallback (covers "under 800", "€700", "around 900", etc.)
BUDGET_PATTS = [
    re.compile(r"(?:under|below|less\s*than|max|at\s*most|<=)\s*[€$]?\s*(\d{2,5})", re.I),
    re.compile(r"(?:around|about|~)\s*[€$]?\s*(\d{2,5})", re.I),
    re.compile(r"[€$]?\s*(\d{2,5})\s*(?:eur|euro|euros|usd|dollars|\$|€)?\b", re.I),
]

def rule_extract_intent(text: str) -> dict:
    t = (text or "").lower()
    out: Dict[str, Any] = {}

    # budget
    for p in BUDGET_PATTS:
        m = p.search(t)
        if m:
            try: out["budget"] = float(m.group(1)); break
            except: pass

    # os
    if any(x in t for x in ["iphone","ios","apple"]): out["os"] = "iOS"
    elif "android" in t: out["os"] = "Android"

    # size
    if any(x in t for x in ["compact","small","6.1","6.0","mini"]):
        out["prefer_small"] = True
    if any(x in t for x in ["large","bigger","6.7","6.8","plus","max"]):
        out["prefer_large"] = True

    # battery/ram/storage (optional)
    m = re.search(r"(\d{3,5})\s*mah", t); 
    if m: out["min_battery"] = int(m.group(1))
    m = re.search(r"(\d{1,2})\s*gb\s*ram", t);
    if m: out["min_ram"] = int(m.group(1))
    m = re.search(r"(\d{2,4})\s*gb(?!\s*ram)", t);
    if m: out["min_storage"] = int(m.group(1))

    # features
    feats = []
    if "wireless" in t: feats.append("wireless charging")
    if "ip68" in t or "waterproof" in t: feats.append("ip68")
    if "esim" in t: feats.append("esim")
    if "5g" in t: feats.append("5g")
    if feats: out["must_have"] = sorted(set(feats))

    # brands preferences / avoid
    known = ["apple","samsung","google","oneplus","xiaomi","sony","motorola","nothing","asus","oppo","vivo","realme","honor","huawei","nokia","lenovo","tecno","infinix"]
    likes, avoids = [], []
    for b in known:
        if re.search(rf"\b{re.escape(b)}\b", t): likes.append(b.title())
        if re.search(rf"\b(avoid|no)\s+{re.escape(b)}\b", t): avoids.append(b.title())
    if likes: out["brands"] = sorted(set(likes))
    if avoids: out["avoid_brands"] = sorted(set(avoids))
    return out

def normalize_intent(d: dict) -> dict:
    out = dict(DEFAULT_INTENT)
    out.update({k:v for k,v in d.items() if v is not None})
    # coerce numbers
    def to_num(x, cast):
        if x in (None, "", [], {}): return None
        try:
            if isinstance(x, str):
                m = re.search(r"\d{1,5}", x)
                if m: x = m.group(0)
            return cast(x)
        except: return None
    for k, cast in [("budget", float), ("min_battery", int), ("min_ram", int), ("min_storage", int), ("min_camera", float), ("min_year", int), ("max_year", int)]:
        out[k] = to_num(out.get(k), cast)

    # booleans
    def to_bool(v):
        if isinstance(v, bool): return v
        if v is None: return None
        s = str(v).strip().lower()
        if s in ["yes","true","1"]: return True
        if s in ["no","false","0"]: return False
        return None
    out["prefer_small"] = to_bool(out.get("prefer_small"))
    out["prefer_large"] = to_bool(out.get("prefer_large"))
    out["camera_priority"] = to_bool(out.get("camera_priority"))

    # arrays
    def to_list(x, title=False):
        if x in (None, "", [], {}): return []
        if isinstance(x, str):
            parts = re.split(r"[,\n;]+", x)
            vals = [p.strip() for p in parts if p.strip()]
        elif isinstance(x, list): vals = [str(p).strip() for p in x if str(p).strip()]
        else: vals = []
        if title: vals = [v.title() for v in vals]
        return sorted(set(vals))
    out["brands"] = to_list(out.get("brands"), title=True)
    out["avoid_brands"] = to_list(out.get("avoid_brands"), title=True)
    out["must_have"] = [v.lower() for v in to_list(out.get("must_have"))]

    # OS nice
    if out.get("os"):
        s = str(out["os"]).lower()
        out["os"] = "iOS" if "ios" in s or "apple" in s or "iphone" in s else ("Android" if "android" in s else None)

    # size conflict
    if out["prefer_small"] and out["prefer_large"]:
        out["prefer_small"] = out["prefer_large"] = None
    return out

# =========================
# Filtering / ranking
# =========================
# change the signature (add strict_budget + compact_max)
def filter_df_by_intent(df: pd.DataFrame, intent: Dict[str, Any], strict_budget: bool = False) -> pd.DataFrame:
    d = df.copy()

    # --- Budget (EUR) ---
    if intent.get("budget") is not None and "PriceEUR" in d.columns:
        try:
            budget = float(intent["budget"])
        except (TypeError, ValueError):
            budget = None
        if budget is not None:
            price = pd.to_numeric(d["PriceEUR"], errors="coerce")
            if strict_budget:
                mask = (~price.isna()) & (price > 0) & (price <= budget)
            else:
                mask = price.isna() | ((price > 0) & (price <= budget))
            d = d.loc[mask].copy()

    # --- OS ---
    if intent.get("os") and "OS" in d.columns:
        s = str(intent["os"]).lower()
        d = d[d["OS"].astype(str).str.lower().str.contains(s, na=False)]

    # --- Year window ---
    if intent.get("min_year") is not None and "ReleaseYear" in d.columns:
        d = d[(d["ReleaseYear"].isna()) | (d["ReleaseYear"] >= int(intent["min_year"]))]
    if intent.get("max_year") is not None and "ReleaseYear" in d.columns:
        d = d[(d["ReleaseYear"].isna()) | (d["ReleaseYear"] <= int(intent["max_year"]))]

    # --- Size ---
    if "DisplayInches" in d.columns:
        if intent.get("prefer_small") is True:
            d = d[(d["DisplayInches"].isna()) | (d["DisplayInches"] <= 6.2)]
        elif intent.get("prefer_large") is True:
            d = d[(d["DisplayInches"].isna()) | (d["DisplayInches"] >= 6.7)]

    # --- Minimums ---
    if intent.get("min_battery") is not None and "Battery_mAh" in d.columns:
        d = d[(d["Battery_mAh"].isna()) | (d["Battery_mAh"] >= int(intent["min_battery"]))]
    if intent.get("min_ram") is not None and "RAM_GB" in d.columns:
        d = d[(d["RAM_GB"].isna()) | (d["RAM_GB"] >= float(intent["min_ram"]))]
    if intent.get("min_storage") is not None and "Storage_GB" in d.columns:
        d = d[(d["Storage_GB"].isna()) | (d["Storage_GB"] >= float(intent["min_storage"]))]
    if intent.get("min_camera") is not None and "MainCameraMP" in d.columns:
        d = d[(d["MainCameraMP"].isna()) | (d["MainCameraMP"] >= float(intent["min_camera"]))]

    # --- Brand include/exclude ---
    if intent.get("brands") and "Brand" in d.columns:
        likes = [str(x).lower() for x in intent["brands"] if x]
        d = d[d["Brand"].astype(str).str.lower().isin(likes)]
    if intent.get("avoid_brands") and "Brand" in d.columns:
        bad = [str(x).lower() for x in intent["avoid_brands"] if x]
        d = d[~d["Brand"].astype(str).str.lower().isin(bad)]

    # --- Features ---
    if intent.get("must_have") and "NotableFeatures" in d.columns:
        nf = d["NotableFeatures"].astype(str).str.lower()
        for feat in intent["must_have"]:
            token = str(feat).strip().lower()
            d = d[nf.str.contains(token, na=False)]

    # --- Sort: newer first, then cheaper (EUR) ---
    if "ReleaseYear" in d.columns:
        d = d.sort_values(["ReleaseYear", "PriceEUR"], ascending=[False, True], na_position="last")
    return d


def rank_df(d: pd.DataFrame, intent: Dict[str, Any]) -> pd.DataFrame:
    if d.empty: return d
    score = (
        (d["ReleaseYear"].fillna(2018) - 2017) * 1.0
        + (d["Battery_mAh"].fillna(3000) / 1000.0) * 0.8
        + (d["MainCameraMP"].fillna(12) / 12.0) * (1.0 if intent.get("camera_priority") else 0.4)
        + (d["RAM_GB"].fillna(4) / 4.0) * 0.3
        + (d["Storage_GB"].fillna(64) / 64.0) * 0.3
    )
    if intent.get("budget"):
        price = d["PriceEUR"].fillna(intent["budget"])
        score += (intent["budget"] - price).clip(lower=-999, upper=500) / 500.0
    return d.assign(_score=score).sort_values(["_score","ReleaseYear"], ascending=[False, False])

# =========================
# Image fetch (Wikipedia)
# =========================
def fetch_phone_image_url(brand: str, model: str) -> Optional[str]:
    try:
        title = f"{brand} {model}".strip()
        r = requests.get("https://en.wikipedia.org/w/api.php", params={
            "action":"query","prop":"pageimages","format":"json","pithumbsize":"640","titles":title
        }, timeout=10)
        thumb = None
        data = r.json().get("query",{}).get("pages",{})
        for _, page in data.items():
            thumb = page.get("thumbnail",{}).get("source")
            if thumb: break
        return thumb
    except Exception:
        return None

# =========================
# LLM pros/cons + blurb
# =========================
def _ollama_text(prompt: str, temp=0.25) -> Optional[str]:
    if not USE_OLLAMA:
        return None
    try:
        r = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
            "options":{"temperature": temp}
        }, timeout=30)
        r.raise_for_status()
        return (r.json().get("response") or "").strip()
    except Exception:
        return None

def _compose_blurb(intent: dict, row: pd.Series) -> Optional[str]:
    """
    3–4 sentences:
    1) What it is and the broad fit.
    2) Connect to user's stated priorities only (size/battery/camera when relevant).
    3) Reviewer sentence from YouTube (if any).
    4) Budget positioning if provided.
    """
    def f(x, cast=float):
        try:
            if pd.notna(x): return cast(x)
        except Exception:
            pass
        return None

    brand  = str(row.get("Brand") or "").strip()
    model  = str(row.get("Model") or "").strip()
    osname = str(row.get("OS") or "").strip()
    year   = int(row.get("ReleaseYear") or 0)
    price  = f(row.get("PriceEUR"))
    disp   = f(row.get("DisplayInches"))
    batt   = f(row.get("Battery_mAh"), int)
    cammp  = f(row.get("MainCameraMP"))
    ram    = f(row.get("RAM_GB"))
    stg    = f(row.get("Storage_GB"))

    # intent
    budget = None
    try:
        budget = float(intent.get("budget")) if intent.get("budget") is not None else None
    except Exception:
        budget = None
    want_small = bool(intent.get("prefer_small"))
    want_large = bool(intent.get("prefer_large"))
    want_camera = bool(intent.get("camera_priority"))
    want_battery = bool(intent.get("min_battery"))

    # YT line
    slug = row.get("Slug")
    try:
        is_nan_slug = pd.isna(slug)
    except Exception:
        is_nan_slug = False
    if not slug or is_nan_slug or str(slug).lower() == "nan":
        slug = _slugify(f"{brand}-{model}")
    yt_line = _yt_review_summary(slug, brand, model, intent)

    # camera mention allowed when user asked OR spec is strong & recent
    allow_camera = want_camera or (cammp and cammp >= 48 and year >= 2022)

    # Try LLM for polished copy first
    if USE_OLLAMA:
        try:
            prompt = (
                "Write 3–4 short sentences (≤ 90 words) that explain why this phone fits the user. "
                "Be clear, friendly, and concrete. Do not list specs; describe benefits.\n"
                "- Mention OS only if the user cares.\n"
                "- Mention size only if user cares (compact/large) with the actual diagonal.\n"
                "- Mention battery only if user cares OR battery ≥ 5000 mAh.\n"
                f"- Mention camera only if allowed_by_camera={bool(allow_camera)}.\n"
                "- If yt_summary is non-empty, include it as exactly ONE sentence.\n"
                "- Finally, position price vs budget if budget is provided.\n\n"
                f"User intent: {json.dumps(intent, ensure_ascii=False)}\n"
                f"Facts: {json.dumps({'brand':brand,'model':model,'os':osname,'year':year,'display_inches':disp,'battery_mAh':batt,'main_camera_mp':cammp,'ram_gb':ram,'storage_gb':stg,'price_usd':price,'budget':budget,'yt_summary':yt_line}, ensure_ascii=False)}\n"
                "Answer:"
            )
            txt = _ollama_text(prompt, temp=0.25) or ""
            txt = re.sub(r"\s+", " ", txt).strip()
            if txt:
                return txt[:500]
        except Exception:
            pass

    # Fallback deterministic
    lines = []

    s1 = f"{brand} {model}"
    if osname and intent.get("os"):
        s1 += f" on {osname}"
    if year:
        s1 += f" ({year})"
    s1 += " looks like a strong match for you."
    lines.append(s1)

    s2p = []
    if disp:
        if want_small and disp <= 6.2:
            s2p.append(f"a compact {disp:.1f}” screen that’s easier to handle")
        elif want_large and disp >= 6.7:
            s2p.append(f"a large {disp:.1f}” display that’s great for reading and video")
    if (want_battery or (batt and batt >= 5000)) and batt:
        s2p.append(f"{batt:,} mAh battery for reliable all-day use")
    if allow_camera and cammp:
        s2p.append("cameras that deliver crisp everyday photos")
    if ram:
        s2p.append(f"{int(ram) if float(ram).is_integer() else ram} GB RAM keeps things responsive")
    if stg:
        s2p.append(f"{int(stg) if float(stg).is_integer() else stg} GB storage leaves room for apps and photos")
    if s2p:
        lines.append("It lines up with your priorities — " + "; ".join(s2p[:3]) + ".")

    if yt_line:
        lines.append(yt_line)

    if budget and price:
        delta = price - budget
        if delta <= 0:
            lines.append(f"It also stays within your €{int(budget)} budget.")
        else:
            lines.append(f"It’s about €{int(round(delta))} over your €{int(budget)} budget.")

    return " ".join(lines)


def llm_pros_cons(intent: dict, row: pd.Series) -> Tuple[List[str], List[str]]:
    prompt = (
        "Return STRICT JSON with keys pros (3-5 items) and cons (2-4 items) for this phone "
        "from the perspective of the user's needs. Keep items short.\n\n"
        f"Intent: {json.dumps(intent, ensure_ascii=False)}\n"
        "Phone: " + json.dumps({
            "Brand": row.get("Brand"), "Model": row.get("Model"),
            "ReleaseYear": int(row.get("ReleaseYear") or 0),
            "PriceEUR": row.get("PriceEUR"),
            "DisplayInches": row.get("DisplayInches"),
            "Battery_mAh": row.get("Battery_mAh"),
            "RAM_GB": row.get("RAM_GB"),
            "Storage_GB": row.get("Storage_GB"),
            "MainCameraMP": row.get("MainCameraMP"),
            "OS": row.get("OS"),
            "NotableFeatures": row.get("NotableFeatures"),
        }, ensure_ascii=False) + "\nJSON:"
    )
    txt = _ollama_text(prompt, temp=0.2)
    if txt:
        try:
            j = json.loads(txt)
            pros = [str(x) for x in (j.get("pros") or [])][:5]
            cons = [str(x) for x in (j.get("cons") or [])][:4]
            if pros or cons:
                return pros, cons
        except Exception:
            pass
    # fallback heuristics
    pros, cons = [], []
    if (row.get("DisplayInches") or 0) >= 6.7: pros.append("Large, immersive display")
    if (row.get("DisplayInches") or 0) <= 6.2: pros.append("Compact size")
    if (row.get("Battery_mAh") or 0) >= 5000: pros.append("Long battery life")
    if (row.get("RAM_GB") or 0) >= 8: pros.append("Plenty of RAM")
    if (row.get("Storage_GB") or 0) >= 256: pros.append("Large storage")
    if (row.get("PriceEUR") or 0) > (intent.get("budget") or 9e9): cons.append("Over your budget")
    if not pros: pros = ["Balanced specs for the price"]
    return pros, cons

# --- Relevance helpers -------------------------------------------------------

_KEYWORDS = {
    "battery": ["battery", "mah", "mAh", "endurance"],
    "ram": ["ram", "memory"],
    "storage": ["storage", "gb", "capacity"],
    "camera": ["camera", "mp", "photo", "telephoto", "ultrawide"],
    "size_small": ["compact", "small", "6.0", "6.1", "one-handed"],
    "size_large": ["large", "big", "6.7", "6.8", "display"],
    "os_ios": ["ios", "iphone", "apple"],
    "os_android": ["android"],
    "wireless": ["wireless charging"],
    "ip68": ["ip68", "water", "dust"],
    "esim": ["esim"],
    "5g": ["5g"],
    "price": ["price", "budget", "expensive", "cheap", "value"]
}

def _intent_keywords(intent: dict) -> set[str]:
    ks: set[str] = set()
    if intent.get("min_battery"): ks.update(_KEYWORDS["battery"])
    if intent.get("min_ram"): ks.update(_KEYWORDS["ram"])
    if intent.get("min_storage"): ks.update(_KEYWORDS["storage"])
    if intent.get("camera_priority"): ks.update(_KEYWORDS["camera"])
    if intent.get("prefer_small"): ks.update(_KEYWORDS["size_small"])
    if intent.get("prefer_large"): ks.update(_KEYWORDS["size_large"])
    if intent.get("os"):
        if str(intent["os"]).lower().startswith("i"):
            ks.update(_KEYWORDS["os_ios"])
        else:
            ks.update(_KEYWORDS["os_android"])
    for f in (intent.get("must_have") or []):
        f = str(f).lower()
        if f == "wireless charging": ks.update(_KEYWORDS["wireless"])
        elif f == "ip68": ks.update(_KEYWORDS["ip68"])
        elif f == "esim": ks.update(_KEYWORDS["esim"])
        elif f == "5g": ks.update(_KEYWORDS["5g"])
    if intent.get("budget") is not None: ks.update(_KEYWORDS["price"])
    return ks

def _filter_bullets_to_intent(pros: list[str], cons: list[str], intent: dict, row: pd.Series, keep_min: int = 3) -> tuple[list[str], list[str]]:
    """Keep bullets that clearly match selected priorities. Never return empty."""
    keys = _intent_keywords(intent)
    def relevant(s: str) -> bool:
        t = str(s or "").lower()
        return any(k in t for k in keys)

    fpros = [p for p in (pros or []) if relevant(p)]
    fcons = [c for c in (cons or []) if relevant(c)]

    # Ensure we still show something:
    target = max(1, min(keep_min, len(pros or [])))
    if len(fpros) < target:
        for p in (pros or []):
            if p not in fpros:
                fpros.append(p)
                if len(fpros) >= target: break
    if not fcons and cons:
        fcons = [cons[0]]

    return fpros, fcons


def _simple_explain(bullet: str, is_con: bool = False) -> str:
    """Tiny heuristic in case LLM is off: 1 short, plain sentence."""
    t = (bullet or "").lower()
    if "battery" in t: return "Longer runtime between charges."
    if "ram" in t: return "More apps stay open without slowdowns."
    if "storage" in t and not is_con: return "Holds more photos, apps, and videos."
    if "storage" in t and is_con:    return "May run out of space quickly."
    if "display" in t or "screen" in t: return "Easier to read and watch videos."
    if "compact" in t: return "Smaller size is easier to hold and pocket."
    if "wireless" in t and "charging" in t: return "Charge by placing it on a pad—no cable needed."
    if "ip68" in t or "water" in t or "dust" in t: return "Better protection from water and dust."
    if "camera" in t or "mp" in t: return "Sharper photos with more detail."
    if "heavy" in t: return "May feel weighty in hand or pocket."
    if "expensive" in t or "price" in t: return "Costs more than similar phones."
    return "Helpful in everyday use." if not is_con else "Potential drawback to consider."


def attach_explanations(intent: dict, row: pd.Series, pros: list[str], cons: list[str]) -> dict:
    """
    Map each bullet to a short plain-language explanation.
    Tries local LLM for JSON; falls back to simple heuristics.
    Returns: {"pros": {...}, "cons": {...}}
    """
    def _simple(bullet: str, is_con: bool = False) -> str:
        t = (bullet or "").lower()
        if "battery" in t: return "Longer runtime between charges."
        if "ram" in t: return "More apps stay open without slowdowns."
        if "storage" in t and not is_con: return "Holds more photos, apps, and videos."
        if "storage" in t and is_con:    return "May run out of space quickly."
        if "display" in t or "screen" in t: return "Easier to read and watch videos."
        if "compact" in t: return "Smaller size is easier to hold and pocket."
        if "wireless" in t and "charging" in t: return "Charge on a pad—no cable in the port."
        if "ip68" in t or "water" in t or "dust" in t: return "Better protection from water and dust."
        if "camera" in t or "mp" in t: return "Sharper photos with more detail."
        if "heavy" in t: return "May feel weighty in hand or pocket."
        if "expensive" in t or "price" in t: return "Costs more than similar phones."
        return "Helpful in everyday use." if not is_con else "Potential drawback to consider."

    out = {"pros": {}, "cons": {}}
    if not pros and not cons:
        return out

    # Try local LLM (Ollama) strict JSON
    try:
        if USE_OLLAMA:
            prompt = (
                "Return STRICT JSON with keys 'pros' and 'cons'. "
                "'pros' maps each pro bullet to a short explanation (<= 18 words). "
                "'cons' does the same for cons. No extra keys or text.\n\n"
                f"Intent: {json.dumps(intent, ensure_ascii=False)}\n"
                "Phone: " + json.dumps({
                    "Brand": row.get("Brand"), "Model": row.get("Model"),
                    "OS": row.get("OS"), "ReleaseYear": int(row.get("ReleaseYear") or 0),
                    "DisplayInches": row.get("DisplayInches"), "Battery_mAh": row.get("Battery_mAh"),
                    "RAM_GB": row.get("RAM_GB"), "Storage_GB": row.get("Storage_GB"),
                    "MainCameraMP": row.get("MainCameraMP")
                }, ensure_ascii=False) +
                f"\nPros: {json.dumps(pros, ensure_ascii=False)}\n"
                f"Cons: {json.dumps(cons, ensure_ascii=False)}\nJSON:"
            )
            j = _ollama_generate_json(prompt) or {}
            if isinstance(j.get("pros"), dict): out["pros"] = j["pros"]
            if isinstance(j.get("cons"), dict): out["cons"] = j["cons"]
    except Exception:
        pass

    # Heuristic fill for any missing bullets
    for p in (pros or []):
        out["pros"].setdefault(p, _simple(p, is_con=False))
    for c in (cons or []):
        out["cons"].setdefault(c, _simple(c, is_con=True))

    return out


def llm_blurb(intent: dict, row: pd.Series) -> Optional[str]:
    prompt = (
        "Write 2 short sentences explaining why this phone fits the user's needs. "
        "Mention key matches (screen size, battery, price vs budget, OS/brand, camera). "
        "No emojis.\n\n"
        f"Intent: {json.dumps(intent, ensure_ascii=False)}\n"
        "Phone: " + json.dumps({
            "Brand": row.get("Brand"), "Model": row.get("Model"),
            "ReleaseYear": int(row.get("ReleaseYear") or 0),
            "PriceEUR": row.get("PriceEUR"),
            "DisplayInches": row.get("DisplayInches"),
            "Battery_mAh": row.get("Battery_mAh"),
            "RAM_GB": row.get("RAM_GB"),
            "Storage_GB": row.get("Storage_GB"),
            "MainCameraMP": row.get("MainCameraMP"),
            "OS": row.get("OS"),
            "NotableFeatures": row.get("NotableFeatures"),
        }, ensure_ascii=False)
    )
    return _ollama_text(prompt, temp=0.25)

# =========================
# UI helper
# =========================
def ui_config() -> dict:
    return {
        "controls": NON_TECH_HINTS,
        "tip": "You can type one message (e.g., 'Android, compact, under 600, long battery') or use the controls and click 'Show results'."
    }




# =========================
# Endpoints
# =========================
@app.get("/healthz")
def healthz():
    from config import PHONES_CSV, USE_LLM, ALLOW_SCRAPERS, DEMO_SEED
    return {
        "ok": True,
        "csv": PHONES_CSV,
        "use_llm": USE_LLM,
        "allow_scrapers": ALLOW_SCRAPERS,
        "demo_seed": DEMO_SEED,
    }

@app.post("/chat/start", response_model=ChatStartResp)
def chat_start():
    sid = str(uuid.uuid4())
    SESSIONS[sid] = {"intent": dict(DEFAULT_INTENT), "skipped": set(), "ask_key": "budget"}
    msg = "Tell me everything in one go, or use the controls. I’ll ask follow-ups if needed."
    return ChatStartResp(session_id=sid, message=msg, ui=ui_config())

def _extract_merge(text: str, current: dict) -> dict:
    # AI first, then rules; only fill empty fields
    ai = ai_extract_intent(text) or {}
    for k, v in ai.items():
        if v not in (None, "", [], {}) and current.get(k) in (None, "", [], {}):
            current[k] = v
    rule = rule_extract_intent(text) or {}
    for k, v in rule.items():
        if v not in (None, "", [], {}) and current.get(k) in (None, "", [], {}):
            current[k] = v
    return current

def _next_question(intent: dict, skipped: set) -> Optional[Tuple[str,str]]:
    for key, phr in SLOTS:
        if key in skipped: 
            continue
        if key == "prefer_small":
            if intent.get("prefer_small") is None and intent.get("prefer_large") is None:
                return key, phr
            continue
        if key in ["brands","must_have"]:
            if not intent.get(key): return key, phr
            continue
        if intent.get(key) is None:
            return key, phr
    return None

def _final_hard_gate(d: pd.DataFrame, intent: dict) -> pd.DataFrame:
    if d is None or d.empty:
        return d
    out = d.copy()
    if intent.get("budget") is not None:
        price = pd.to_numeric(out["PriceEUR"], errors="coerce")
        b = float(intent["budget"])
        out = out[(~price.isna()) & (price > 0) & (price <= b)]
    # avoid_brands and os filters same as before
    return out


# ---------------------------------------------------


def _answer_or_ask(intent: dict, skipped: set, user_text: str) -> tuple[Optional[str], Optional[list], int]:
    """
    While asking: return the next prompt + a live count.
    When answering: never return picks that violate the user's budget.
    """
    lower = (user_text or "").lower()
    force_answer = bool(re.search(r"\b(show\s*results|results|recommend|suggest|buy|best|pick|choose)\b", lower))

    # default year
    if intent.get("min_year") is None and intent.get("max_year") is None:
        intent["min_year"] = 2018

    # still collecting? -> ask next (unless forced)
    nq = _next_question(intent, skipped)
    if nq and not force_answer:
        key, prompt = nq
        try:
            live = filter_df_by_intent(safe_df(), intent)
            live = _strict_budget_df(live, intent.get("budget"))
            return prompt, None, int(len(live))
        except Exception as e:
            print("[live-count] failed:", e)
            return prompt, None, 0

    # time to answer
    try:
        try:
            df_cand, relaxed_intent, note = candidates_multi(intent)
        except Exception as e:
            print("[candidates_multi] failed:", e)
            df_cand = filter_df_by_intent(safe_df(), intent)
            relaxed_intent = intent
            note = "soft filter fallback"

        # persist any relaxed fields
        for k, v in (relaxed_intent or {}).items():
            intent[k] = v

        # FINAL hard budget gate (even after relaxations)
        df_cand = _strict_budget_df(df_cand, intent.get("budget"))

        # absolute fallback: still honor budget
        if df_cand is None or df_cand.empty:
            df_cand = safe_df().sort_values(
                ["ReleaseYear", "PriceEUR"], ascending=[False, True], na_position="last"
            )
            df_cand = _strict_budget_df(df_cand, intent.get("budget"))

        # build cards, cap to 3, enforce budget again on picks
        picks = _build_picks_from_df(df_cand, intent)
        picks = _strict_budget_picks(picks, intent.get("budget"))[:3]

        # count (strict)
        try:
            count = len(_strict_budget_df(filter_df_by_intent(safe_df(), intent), intent.get("budget")))
        except Exception:
            count = len(df_cand)

        # blurb: use featured card's per-pick blurb; fall back to df-row blurb; then generic
        ask = None
        if picks:
            ask = (picks[0] or {}).get("Blurb") or None
        if not ask and picks:
            try:
                if not df_cand.empty:
                    ask = _blurb_for_row(intent, df_cand.iloc[0]) or None
            except Exception as e:
                print("[blurb fallback] failed:", e)
                ask = None
        if not ask and picks:
            top = picks[0]
            ask = f"I’d start with {top['Brand']} {top['Model']} — strong match for what you asked."


        return ask, picks, int(count)

    except Exception as e:
        print("[_answer_or_ask] fatal:", e)
        df_top = _strict_budget_df(
            safe_df().sort_values(["ReleaseYear", "PriceEUR"], ascending=[False, True], na_position="last"),
            intent.get("budget"),
        )
        picks = _strict_budget_picks(_build_picks_from_df(df_top, intent), intent.get("budget"))[:3]
        ask = "Here are solid recent options while I sort out that hiccup."
        return ask, picks, int(len(df_top or []))


    # Search
    base = safe_df()
    d = filter_df_by_intent(base, intent, strict_budget=True)

    # Relaxations (soft) to reach at least 3 options (but without violating *hard* constraints later)
    if len(d) < 3:
        tmp = dict(intent)
        changed = False
        if tmp.get("must_have"):
            tmp["must_have"] = []
            changed = True
        if len(filter_df_by_intent(base, tmp)) < 3 and tmp.get("min_battery"):
            tmp["min_battery"] = int(tmp["min_battery"] * 0.9)
            changed = True
        d = filter_df_by_intent(base, tmp) if changed else d

    # Final hard gate — never return over-budget / disliked / OS-mismatched
    d = _final_hard_gate(d, intent)

    # If nothing and user has budget/avoid/os, ask to relax
    if d.empty and (intent.get("budget") is not None or intent.get("avoid_brands") or intent.get("os")):
        return ("I couldn’t find matches within your constraints. Should I relax them a bit (e.g., +15% budget or ignore OS)?", None, 0)

    # If still empty, show general top picks
    if d.empty:
        base = base.sort_values(["ReleaseYear","PriceEUR"], ascending=[False, True], na_position="last")
        d = base.head(30)

    ranked = unique_topn(rank_df(d, intent), 3)
    picks = _build_picks(ranked, intent)

    return (llm_blurb(intent, ranked.iloc[0]) or "Here’s what I recommend.", picks, int(len(d)))

# ---------- chat/message ----------

_RATE = {}  # ip -> [timestamps]


def allow(ip: str | None, limit: int = 30, window: int = 60) -> bool:
    """
    Simple sliding-window rate limiter keyed by IP (None-safe).
    Uses epoch seconds from time.time().
    """
    key = ip or "unknown"
    now = _time.time()
    recent = [t for t in _RATE.get(key, []) if now - t < window]
    recent.append(now)
    _RATE[key] = recent
    return len(recent) <= limit


@app.post("/chat/message", response_model=ChatMessageResp)
def chat_message(req: ChatMessageReq, request: Request):
    # --- Safe client IP (works with proxies and when request.client is None) ---
    try:
        ip = _client_ip(request)  # uses your helper defined earlier
    except Exception:
        ip = "unknown"

    # --- Throttle ---
    if not allow(ip):
        return ChatMessageResp(
            session_id=req.session_id,
            intent=SESSIONS.get(req.session_id, {}).get("intent", DEFAULT_INTENT),
            ask="Too many requests—please slow down a bit.",
            picks=None,
            count=0,
            ui=ui_config(),
        )

    try:
        # ---- session bootstrap
        sess = SESSIONS.get(req.session_id) or {
            "intent": dict(DEFAULT_INTENT),
            "skipped": set(),
            "ask_key": "budget",
        }
        intent = dict(sess.get("intent", DEFAULT_INTENT))
        skipped = set(sess.get("skipped", set()))
        text = (req.message or "").strip()
        lower_text = text.lower()

        # ---- allow "skip" for the last asked slot
        if wants_to_skip(text) and sess.get("ask_key"):
            skipped.add(sess["ask_key"])

        # ---- ultra-early budget catch: plain "700" / "€700" / "700 euro"
        m_budget = re.fullmatch(r"\s*(\d{2,5})(?:\s*(?:usd|dollars|\€))?\s*€", text, re.I)
        if m_budget and intent.get("budget") in (None, "", 0):
            try:
                intent["budget"] = float(m_budget.group(1))
            except Exception:
                pass

        # ---- merge AI + rules into intent (only fill empties), then normalize
        intent = _extract_merge(text, intent)
        intent = normalize_intent(intent)

        # ---- FAST-PATH: user explicitly asked to see results now
        if re.search(r"\b(show\s*results|show\s*now|results|recommend|suggest|pick|choose|buy)\b", lower_text):
            # persist current intent before jumping to results
            sess["intent"] = intent
            sess["skipped"] = skipped
            SESSIONS[req.session_id] = sess
            # strict compute + return (no extra questioning, no over-relaxing)
            return _direct_results_response(req.session_id, intent, skipped)

        # ---- normal flow: decide whether to ask next question or answer now
        ask, picks, count = _answer_or_ask(intent, skipped, text)

        # ---- save session snapshot
        sess["intent"] = intent
        sess["skipped"] = skipped
        SESSIONS[req.session_id] = sess

        # ---- respond
        return ChatMessageResp(
    session_id=req.session_id,
    intent=intent,
    ask=ask,
    picks=[_clean_pick(p) for p in (picks or []) if isinstance(p, dict)],
    count=int(count or 0),
    ui=ui_config(),
        )

    except Exception as e:
        # keep the session intent if available so UI doesn't reset
        safe_intent = SESSIONS.get(req.session_id, {}).get("intent", dict(DEFAULT_INTENT))
        return ChatMessageResp(
            session_id=req.session_id,
            intent=safe_intent,
            ask=f"Sorry — internal error ({e.__class__.__name__}). You can continue or type 'show results'.",
            picks=None,
            count=0,
            ui=ui_config(),
        )

# ---------- chat/patch (from UI controls; no NLP) ----------
from pydantic import BaseModel

class PatchReq(BaseModel):
    session_id: str
    patch: dict

@app.post("/chat/patch", response_model=ChatMessageResp)
def chat_patch(req: PatchReq):
    try:
        sess = SESSIONS.get(req.session_id) or {"intent": dict(DEFAULT_INTENT), "skipped": set(), "ask_key": "budget"}
        intent = dict(sess.get("intent", DEFAULT_INTENT))

        # merge incoming partial
        patch = req.patch or {}
        for k, v in patch.items():
            intent[k] = v  # allow setting None (reset)

        # normalize so filters are consistent
        intent = normalize_intent(intent)

        # save session
        sess["intent"] = intent
        SESSIONS[req.session_id] = sess

        # just compute a count; DO NOT build picks here
        try:
            d = filter_df_by_intent(safe_df(), intent)
            count = int(d.shape[0])
        except Exception:
            count = 0

        return ChatMessageResp(
            session_id=req.session_id,
            intent=intent,
            ask=None,
            picks=None,
            count=count,
            ui=ui_config(),
        )
    except Exception as e:
        # return previous intent so UI doesn't "freeze"
        sess = SESSIONS.get(req.session_id) or {"intent": dict(DEFAULT_INTENT)}
        return ChatMessageResp(
            session_id=req.session_id,
            intent=sess.get("intent", dict(DEFAULT_INTENT)),
            ask=f"Sorry — patch error ({e.__class__.__name__}).",
            picks=None,
            count=0,
            ui=ui_config(),
        )


