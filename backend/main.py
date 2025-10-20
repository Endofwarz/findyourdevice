from __future__ import annotations
from config import PHONES_CSV, USE_LLM, ALLOW_SCRAPERS, DEMO_SEED
import random
if DEMO_SEED:
    try: random.seed(int(DEMO_SEED))
    except: random.seed(42)

import os, re, json, uuid, math
from typing import Any, Dict, List, Optional, Tuple
import time  # needed by _build_picks_from_df
import pandas as pd
import requests           
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Request
DIAG = os.getenv("DIAG", "1") == "1"   # turn off by setting DIAG=0

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

app = FastAPI()

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

import csv, pathlib

def _load_youtube_signals(slug: str) -> tuple[list, list]:
    """
    Reads data/processed/reviews.csv and returns (pros, cons) for this slug, or ([], []).
    """
    path = pathlib.Path("data/processed/reviews.csv")
    if not path.exists():
        return [], []
    try:
        with path.open(encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                if (row.get("slug") or "") == slug:
                    pros = (row.get("pros") or "").split("|") if row.get("pros") else []
                    cons = (row.get("cons") or "").split("|") if row.get("cons") else []
                    return pros, cons
    except Exception:
        pass
    return [], []
# =========================
# Config
# =========================
CSV_PATH = os.getenv("PHONES_CSV", "data/processed/phones_clean.csv")

USE_OLLAMA = os.getenv("USE_OLLAMA", "1") == "1"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")  # good balance offline

# =========================
# FastAPI
# =========================
app = FastAPI(title="Phone Finder API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or your explicit list if you prefer
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"ok": True, "docs": "/docs", "health": "/healthz"}
# =========================
# Session store
# =========================
SESSIONS: Dict[str, Dict[str, Any]] = {}

# =========================
# Data loading
# =========================
_DF_CACHE: Optional[pd.DataFrame] = None

EXPECTED_COLS = [
    "ID","Brand","Model","Slug","ReleaseYear","PriceUSD","DisplayInches",
    "Battery_mAh","RAM_GB","Storage_GB","MainCameraMP","OS","Weight_g",
    "NotableFeatures","SourceFiles"
]

def load_df() -> pd.DataFrame:
    global _DF_CACHE
    if _DF_CACHE is not None:
        return _DF_CACHE
    if not os.path.exists(CSV_PATH):
        _DF_CACHE = pd.DataFrame(columns=EXPECTED_COLS)
        return _DF_CACHE

    df = pd.read_csv(CSV_PATH, low_memory=False)
    for c in EXPECTED_COLS:
        if c not in df.columns:
            df[c] = None

    # numeric coercion
    to_num = {
        "ReleaseYear":"Int64", "PriceUSD":"float", "DisplayInches":"float",
        "Battery_mAh":"Int64", "RAM_GB":"float", "Storage_GB":"float",
        "MainCameraMP":"float", "Weight_g":"float"
    }
    for c, _ in to_num.items():
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # realistic price fallback if missing
    df["PriceUSD"] = df["PriceUSD"].where((df["PriceUSD"] > 20) & df["PriceUSD"].notna())
    df["PriceUSD"] = df.apply(_price_fallback, axis=1)

    # strip strings
    for c in ["Brand","Model","OS","NotableFeatures","Slug"]:
        df[c] = df[c].astype(str).str.strip()

    _DF_CACHE = df
    return _DF_CACHE

def _price_fallback(row: pd.Series) -> Optional[float]:
    """Simple heuristic if dataset price missing."""
    p = row.get("PriceUSD")
    if isinstance(p, (int,float)) and p and p > 20:
        return float(p)
    year = int(row.get("ReleaseYear") or 0)
    ram = float(row.get("RAM_GB") or 0)
    storage = float(row.get("Storage_GB") or 0)
    brand = (row.get("Brand") or "").lower()
    base = 250.0
    if year >= 2024: base += 150
    elif year >= 2022: base += 80
    base += (ram * 18.0) + (storage/128.0)*50.0
    if brand in ["apple","samsung","google","sony","asus","oneplus"]:
        base *= 1.2
    return round(max(base, 120.0), 2)

def safe_df() -> pd.DataFrame:
    return load_df().copy()

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
    "budget": {"type":"slider", "min":100, "max":2000, "step":50, "unit":"$"},
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
        # block NaN/inf
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v
    except Exception:
        return None

def _clean_pick(p: dict) -> dict:
    """Ensure every field is JSON-safe (no NaN/inf/custom types)."""
    q = dict(p or {})
    # numeric fields
    for k, caster in [
        ("ReleaseYear", int), ("PriceUSD", float), ("DisplayInches", float),
        ("Battery_mAh", int), ("RAM_GB", float), ("Storage_GB", float),
        ("MainCameraMP", float), ("Weight_g", float),
    ]:
        if k in q:
            q[k] = _json_safe_num(q[k], caster)
    # strings: coerce non-strings to strings or None
    for k in ["Brand","Model","OS","NotableFeatures","ImageURL","ImageLocal","BrandLogo"]:
        if k in q:
            q[k] = None if q[k] is None else str(q[k])
    # arrays
    for k in ["Pros","Cons"]:
        if k in q and not isinstance(q[k], list):
            q[k] = []
        if isinstance(q.get(k), list):
            q[k] = [str(x) for x in q[k] if x is not None][:10]
    # LiveOffer object cleanup if present
    if isinstance(q.get("LiveOffer"), dict):
        offer = q["LiveOffer"]
        q["LiveOffer"] = {
            "retailer": str(offer.get("retailer") or ""),
            "price": _json_safe_num(offer.get("price"), float),
            "currency": str(offer.get("currency") or "USD"),
            "url": str(offer.get("url") or ""),
            "in_stock": bool(offer.get("in_stock")),
        }
    return q


def _strict_budget_df(d: pd.DataFrame, budget) -> pd.DataFrame:
    """Return only rows with a known positive price <= budget. No-op when budget is None."""
    if d is None or d.empty or budget in (None, "", 0):
        return d
    price = pd.to_numeric(d["PriceUSD"], errors="coerce")
    return d.loc[(~price.isna()) & (price > 0) & (price <= float(budget))].copy()

def _none_if_nan(x):
    try:
        import math
        return None if (x is None or (isinstance(x, float) and math.isnan(x))) else x
    except Exception:
        return x

def _strict_budget_picks(picks: list[dict], budget) -> list[dict]:
    """Keep only picks priced <= budget (when known)."""
    if not picks or budget in (None, "", 0):
        return picks or []
    b = float(budget)
    out = []
    for p in picks:
        try:
            price = float(p.get("PriceUSD") or 0)
        except Exception:
            price = 0
        if price and price <= b:
            out.append(p)
    return out

def _blurb_for_row(intent: dict, row: pd.Series) -> Optional[str]:
    """
    Try LLM blurb (chat_complete) → local _compose_blurb → llm_blurb → None.
    """
    # LLM-first (Groq/OpenAI via chat_complete)
    try:
        if USE_LLM:
            facts = {
                "Brand": str(row.get("Brand") or "").strip(),
                "Model": str(row.get("Model") or "").strip(),
                "OS": str(row.get("OS") or "").strip(),
                "ReleaseYear": int(row.get("ReleaseYear") or 0),
                "PriceUSD": row.get("PriceUSD"),
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
                    return txt[:500]
    except Exception as _e:
        print("[LLM blurb] fallback:", _e)

    # Local helper
    try:
        txt = _compose_blurb(intent, row)
        if txt:
            return txt
    except Exception:
        pass

    # Optional alternate
    try:
        txt = llm_blurb(intent, row)
        if txt:
            return txt
    except Exception:
        pass

    return None



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
        d = safe_df().sort_values(["ReleaseYear", "PriceUSD"], ascending=[False, True], na_position="last")
        d = _strict_budget_df(d, intent.get("budget"))

    count = int(len(d))

    # rank + build (cap to 3)
    ranked = rank_df(d, intent)
    picks = _build_picks_from_df(ranked.head(30), intent)
    picks = _strict_budget_picks(picks, intent.get("budget"))[:3]

    # blurb
    ask = None
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
    """
    Progressive selection so final picks never end at 0:
    strict budget -> soft budget -> drop must-have -> budget +15% -> drop size ->
    relax minimums -> drop budget (penalize later) -> fallback newest.
    Returns (df, possibly_modified_intent, note).
    """
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
    base = df_all.sort_values(["ReleaseYear","PriceUSD"], ascending=[False, True], na_position="last")
    return base.head(30), i0, "fallback newest"

def _build_picks_from_df(d: pd.DataFrame, intent: dict) -> list[dict]:
    """
    Non-invasive builder with local brand/phone assets + remote image + pros/cons.
    Keeps the same signature so existing call sites don't change.
    """
    picks: list[dict] = []
    if d is None or d.empty:
        return picks

    # Rank + dedupe like before
    try:
        ranked = rank_df(d, intent)
    except Exception as e:
        print("[rank_df] failed:", e)
        ranked = d
    try:
        ranked = unique_topn(ranked, 6)  # show a few more; UI will cut as needed
    except Exception as e:
        print("[unique_topn] failed:", e)
        ranked = ranked.head(6)

    for _, row in ranked.iterrows():
        # --- Remote image (best-effort) ---
        image_url = None
        try:
            image_url = fetch_phone_image_url(str(row.get("Brand") or ""), str(row.get("Model") or ""))
        except Exception as e:
            print("[image] fetch_phone_image_url failed:", e)

        # --- Local offline assets (public/phones, public/brands) ---
        brand = (row.get("Brand") or "").strip()
        model = (row.get("Model") or "").strip()
        slug = row.get("Slug")

        # guard NaN slugs
        try:
            is_nan_slug = pd.isna(slug)
        except Exception:
            is_nan_slug = False
        if not slug or is_nan_slug or str(slug).lower() == "nan":
            slug = _slugify(f"{brand}-{model}")

        phone_local = (
            _public_url_if_exists(f"/phones/{slug}.jpg")
            or _public_url_if_exists(f"/phones/{slug}.png")
        )

        brand_key = brand.lower().replace(" ", "_")
        brand_logo = _public_url_if_exists(f"/brands/{brand_key}.png")

        # --- Pros/Cons (LLM first; fallback heuristics) ---
        pros, cons = [], []
        try:
            if USE_LLM:
                facts = {
                    "Brand": brand, "Model": model,
                    "OS": row.get("OS"),
                    "ReleaseYear": int(row.get("ReleaseYear") or 0),
                    "PriceUSD": row.get("PriceUSD"),
                    "DisplayInches": row.get("DisplayInches"),
                    "Battery_mAh": row.get("Battery_mAh"),
                    "RAM_GB": row.get("RAM_GB"),
                    "Storage_GB": row.get("Storage_GB"),
                    "MainCameraMP": row.get("MainCameraMP"),
                    "NotableFeatures": row.get("NotableFeatures"),
                }
                msgs = pros_cons_messages(intent, facts)
                txt = chat_complete(msgs, max_tokens=220, temperature=0.2)
                if txt:
                    import json as _json, re as _re
                    j = None
                    try:
                        j = _json.loads(txt)
                    except _json.JSONDecodeError:
                        m = _re.search(r"\{.*\}", txt, _re.S)
                        if m:
                            try:
                                j = _json.loads(m.group(0))
                            except Exception:
                                j = None
                    if isinstance(j, dict):
                        pros = [str(x) for x in (j.get("pros") or [])][:5]
                        cons = [str(x) for x in (j.get("cons") or [])][:4]
            if not pros and not cons:
                try:
                    pros, cons = llm_pros_cons(intent, row) or ([], [])
                except Exception:
                    pros, cons = [], []
        except Exception as e:
            print("[pros/cons] LLM failed:", e)
            pros, cons = [], []

        # --- Merge YouTube review signals BEFORE building item ---
        try:
            yt_pros, yt_cons = _load_youtube_signals(slug)
            def _merge(a, b, limit):
                out, seen = [], set()
                for x in (a or []) + (b or []):
                    s = (x or "").strip()
                    if not s:
                        continue
                    if s not in seen:
                        seen.add(s); out.append(s)
                    if len(out) >= limit:
                        break
                return out
            pros = _merge(pros, yt_pros, 5)
            cons = _merge(cons, yt_cons, 4)
        except Exception as _e:
            print("[yt-merge] failed:", _e)

        # --- Align bullets to the user's intent ---
        try:
            pros, cons = _filter_bullets_to_intent(pros, cons, intent, row)
        except Exception as e:
            print("[pros/cons-filter] failed:", e)

        # --- Build item safely (after merges) ---
        def fnum(x, cast):
            try:
                return cast(x) if pd.notna(x) else None
            except Exception:
                return None

        item = {
            "Brand": row.get("Brand"),
            "Model": row.get("Model"),
            "ReleaseYear": fnum(row.get("ReleaseYear"), int) or 0,
            "PriceUSD": fnum(row.get("PriceUSD"), float) or 0.0,
            "DisplayInches": fnum(row.get("DisplayInches"), float),
            "Battery_mAh": fnum(row.get("Battery_mAh"), int),
            "RAM_GB": fnum(row.get("RAM_GB"), float),
            "Storage_GB": fnum(row.get("Storage_GB"), float),
            "MainCameraMP": fnum(row.get("MainCameraMP"), float),
            "OS": row.get("OS"),
            "Weight_g": fnum(row.get("Weight_g"), float),
            "NotableFeatures": row.get("NotableFeatures"),
            "ImageLocal": phone_local,
            "ImageURL": image_url,
            "BrandLogo": brand_logo,
            "Pros": pros,
            "Cons": cons,
        }

        # Live offer (if present)
        try:
            offer = best_offer_for_slug(slug)
            if offer:
                item["LiveOffer"] = offer
        except Exception as _e:
            print("[offers] attach failed:", _e)

        # Tooltip explanations
        try:
            item["Explain"] = attach_explanations(intent, row, pros, cons)
        except Exception as _e:
            print("[explain] failed:", _e)

        picks.append(item)

    return picks



@app.get("/yt/status")
def yt_status():
    import pathlib, csv as _csv
    p = pathlib.Path("data/processed/reviews.csv")
    rows = 0
    if p.exists():
        with p.open(encoding="utf-8") as f:
            rows = sum(1 for _ in _csv.DictReader(f))
    return {"exists": p.exists(), "rows": rows}

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
        "- Budget: numeric USD if 'under/<=/max $X' or a number appears.\n"
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

# Strong regex fallback (covers "under 800", "$700", "around 900", etc.)
BUDGET_PATTS = [
    re.compile(r"(?:under|below|less\s*than|max|at\s*most|<=)\s*\$?\s*(\d{2,5})", re.I),
    re.compile(r"(?:around|about|~)\s*\$?\s*(\d{2,5})", re.I),
    re.compile(r"\$?\s*(\d{2,5})\s*(?:usd|dollars|\$)?\b", re.I),
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

    # --- Budget ---
    if intent.get("budget") is not None and "PriceUSD" in d.columns:
        try:
            budget = float(intent["budget"])
        except (TypeError, ValueError):
            budget = None

        if budget is not None:
            price = pd.to_numeric(d["PriceUSD"], errors="coerce")
            if strict_budget:
                # strict: known positive price <= budget
                mask = (~price.isna()) & (price > 0) & (price <= budget)
            else:
                # soft: allow unknown price rows (NaN) + <= budget
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

    # --- Sort: newer first, then cheaper ---
    if "ReleaseYear" in d.columns:
        d = d.sort_values(["ReleaseYear", "PriceUSD"], ascending=[False, True], na_position="last")

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
        price = d["PriceUSD"].fillna(intent["budget"])
        score += (intent["budget"] - price).clip(lower=-999, upper=500) / 500.0
    return d.assign(_score=score).sort_values(["_score","ReleaseYear"], ascending=[False, False])

def unique_topn(df: pd.DataFrame, n: int = 3) -> pd.DataFrame:
    if df.empty: return df
    if df["Slug"].notna().any():
        df = df.drop_duplicates(subset=["Slug"])
    else:
        df = df.drop_duplicates(subset=["Brand","Model"])
    return df.head(n)

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
    Return 3–4 short, friendly sentences explaining *why this phone fits the user*.
    Prefers the local LLM (Ollama) but falls back to a clear heuristic so it never fails.
    """
    # --- safe getters ---
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
    price  = f(row.get("PriceUSD"))
    disp   = f(row.get("DisplayInches"))
    batt   = f(row.get("Battery_mAh"), int)
    cammp  = f(row.get("MainCameraMP"))
    ram    = f(row.get("RAM_GB"))
    stg    = f(row.get("Storage_GB"))

    budget = None
    try:
        budget = float(intent.get("budget")) if intent.get("budget") is not None else None
    except Exception:
        budget = None

    # --- build a compact facts block for the prompt ---
    wants = {
        "os": intent.get("os"),
        "prefer_small": intent.get("prefer_small"),
        "prefer_large": intent.get("prefer_large"),
        "min_battery": intent.get("min_battery"),
        "min_ram": intent.get("min_ram"),
        "min_storage": intent.get("min_storage"),
        "camera_priority": intent.get("camera_priority"),
        "budget": budget,
    }
    facts = {
        "brand": brand, "model": model, "os": osname, "year": year,
        "display_inches": disp, "battery_mAh": batt, "main_camera_mp": cammp,
        "ram_gb": ram, "storage_gb": stg, "price_usd": price
    }

    # --- LLM-first version (plain text, no JSON needed) ---
    if USE_OLLAMA:
        try:
            prompt = (
                "Write 3–4 short, friendly sentences for a non-technical shopper "
                "explaining why this phone fits what they asked. "
                "Use simple words. Mention OS if relevant, size match (compact/large), "
                "battery longevity, camera if prioritized, and budget fit (within/over). "
                "Avoid specs soup—explain benefits. No bullets, no emojis, 60–80 words max.\n\n"
                f"User intent:\n{json.dumps(wants, ensure_ascii=False)}\n\n"
                f"Phone facts:\n{json.dumps(facts, ensure_ascii=False)}\n\n"
                "Answer:"
            )
            txt = _ollama_text(prompt, temp=0.25) or ""
            txt = re.sub(r"\s+", " ", txt).strip()
            if txt:
                return txt[:500]
        except Exception:
            pass

    # --- Heuristic fallback (no LLM) ---
    lines = []

    # Sentence 1: what it is + OS + recency
    part_os = f" on {osname}" if osname else ""
    part_year = f" from {year}" if year else ""
    lines.append(f"{brand} {model}{part_os}{part_year} looks like a strong match for you.")

    # Sentence 2: size + battery + camera
    s2 = []
    if disp:
        if intent.get("prefer_small") and disp <= 6.2:
            s2.append(f"the {disp:.1f}” screen keeps it easy to handle")
        elif intent.get("prefer_large") and disp >= 6.7:
            s2.append(f"the big {disp:.1f}” display is great for reading and photos")
        else:
            s2.append(f"the {disp:.1f}” screen balances size and comfort")
    if (intent.get("min_battery") or 0) >= 4500 and batt:
        s2.append(f"{batt:,} mAh battery should comfortably last a day")
    if intent.get("camera_priority") and cammp:
        s2.append("the camera is strong for everyday photos")
    if s2:
        lines.append("It suits your preferences — " + "; ".join(s2) + ".")

    # Sentence 3: RAM/storage plain benefit
    s3 = []
    if ram:
        s3.append(f"{int(ram) if float(ram).is_integer() else ram} GB RAM helps it stay responsive")
    if stg:
        s3.append(f"{int(stg) if float(stg).is_integer() else stg} GB gives plenty of space")
    if s3:
        lines.append("You’ll feel it in daily use — " + " and ".join(s3) + ".")

    # Sentence 4: budget position
    if budget and price:
        delta = price - budget
        if delta <= 0:
            lines.append(f"It also stays within your ${int(budget)} budget.")
        else:
            lines.append(f"It’s about ${int(round(delta))} over your ${int(budget)} budget; "
                         "I included cheaper alternatives below.")

    return " ".join(lines)


def llm_pros_cons(intent: dict, row: pd.Series) -> Tuple[List[str], List[str]]:
    prompt = (
        "Return STRICT JSON with keys pros (3-5 items) and cons (2-4 items) for this phone "
        "from the perspective of the user's needs. Keep items short.\n\n"
        f"Intent: {json.dumps(intent, ensure_ascii=False)}\n"
        "Phone: " + json.dumps({
            "Brand": row.get("Brand"), "Model": row.get("Model"),
            "ReleaseYear": int(row.get("ReleaseYear") or 0),
            "PriceUSD": row.get("PriceUSD"),
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
    if (row.get("PriceUSD") or 0) > (intent.get("budget") or 9e9): cons.append("Over your budget")
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
            "PriceUSD": row.get("PriceUSD"),
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
    """Always enforce strict budget and avoid_brands, and OS if specified."""
    if d is None or d.empty:
        return d
    out = d.copy()
    if intent.get("budget") is not None:
        price = pd.to_numeric(out["PriceUSD"], errors="coerce")
        b = float(intent["budget"])
        out = out[(~price.isna()) & (price > 0) & (price <= b)]
    if intent.get("avoid_brands"):
        bad = [s.lower() for s in intent["avoid_brands"]]
        out = out[~out["Brand"].str.lower().isin(bad)]
    if intent.get("os"):
        s = intent["os"].lower()
        if s.startswith("i"):
            out = out[(out["OS"].str.contains("ios", case=False, na=False)) | (out["Brand"].str.contains("apple", case=False, na=False))]
        elif s.startswith("a"):
            out = out[~((out["OS"].str.contains("ios", case=False, na=False)) | (out["Brand"].str.contains("apple", case=False, na=False)))]
    return out

def _build_picks(ranked: pd.DataFrame, intent: dict) -> List[dict]:
    picks: List[dict] = []

    for _, row in ranked.iterrows():
        # --- Remote image (may be None) ---
        try:
            image_url = fetch_phone_image_url(
                str(row.get("Brand") or ""),
                str(row.get("Model") or "")
            )
        except Exception:
            image_url = None

        # --- Local offline assets (public/phones, public/brands) ---
        brand = (row.get("Brand") or "").strip()
        model = (row.get("Model") or "").strip()
        slug = row.get("Slug")

        # guard NaN slugs
        try:
            is_nan_slug = pd.isna(slug)
        except Exception:
            is_nan_slug = False

        if not slug or is_nan_slug or str(slug).lower() == "nan":
            slug = _slugify(f"{brand}-{model}")

        phone_local = (
            _public_url_if_exists(f"/phones/{slug}.jpg")
            or _public_url_if_exists(f"/phones/{slug}.png")
        )

        brand_key = brand.lower().replace(" ", "_")  # "OnePlus" -> "oneplus"
        brand_logo = _public_url_if_exists(f"/brands/{brand_key}.png")  # PNG logos you generated

               # --- Pros/Cons (Groq/LLM first; fallback heuristics) ---
        pros, cons = [], []
        try:
            if USE_LLM:
                facts = {
                    "Brand": brand, "Model": model,
                    "OS": row.get("OS"),
                    "ReleaseYear": int(row.get("ReleaseYear") or 0),
                    "PriceUSD": row.get("PriceUSD"),
                    "DisplayInches": row.get("DisplayInches"),
                    "Battery_mAh": row.get("Battery_mAh"),
                    "RAM_GB": row.get("RAM_GB"),
                    "Storage_GB": row.get("Storage_GB"),
                    "MainCameraMP": row.get("MainCameraMP"),
                    "NotableFeatures": row.get("NotableFeatures"),
                }
                msgs = pros_cons_messages(intent, facts)
                txt = chat_complete(msgs, max_tokens=220, temperature=0.2)
                if txt:
                    import json as _json, re as _re
                    j = None
                    try:
                        j = _json.loads(txt)
                    except _json.JSONDecodeError:
                        m = _re.search(r"\{.*\}", txt, _re.S)
                        if m:
                            try: j = _json.loads(m.group(0))
                            except Exception: j = None
                    if isinstance(j, dict):
                        pros = [str(x) for x in (j.get("pros") or [])][:5]
                        cons = [str(x) for x in (j.get("cons") or [])][:4]
            if not pros and not cons:
                try:
                    pros, cons = llm_pros_cons(intent, row) or ([], [])
                except Exception:
                    pros, cons = [], []
        except Exception as e:
            print("[pros/cons] LLM failed:", e)
            pros, cons = [], []

        # --- Merge YouTube review signals BEFORE building item ---
        try:
            yt_pros, yt_cons = _load_youtube_signals(slug)
            def _merge(a, b, limit):
                out, seen = [], set()
                for x in (a or []) + (b or []):
                    s = (x or "").strip()
                    if not s:
                        continue
                    if s not in seen:
                        seen.add(s); out.append(s)
                    if len(out) >= limit:
                        break
                return out
            pros = _merge(pros, yt_pros, 5)
            cons = _merge(cons, yt_cons, 4)
        except Exception as _e:
            print("[yt-merge] failed:", _e)

        # --- Align bullets to the user's intent ---
        try:
            pros, cons = _filter_bullets_to_intent(pros, cons, intent, row)
        except Exception as e:
            print("[pros/cons-filter] failed:", e)

        # --- Build item safely (after merges) ---
        def fnum(x, cast):
            try:
                return cast(x) if pd.notna(x) else None
            except Exception:
                return None

        item = {
            "Brand": row.get("Brand"),
            "Model": row.get("Model"),
            "ReleaseYear": fnum(row.get("ReleaseYear"), int) or 0,
            "PriceUSD": fnum(row.get("PriceUSD"), float) or 0.0,
            "DisplayInches": fnum(row.get("DisplayInches"), float),
            "Battery_mAh": fnum(row.get("Battery_mAh"), int),
            "RAM_GB": fnum(row.get("RAM_GB"), float),
            "Storage_GB": fnum(row.get("Storage_GB"), float),
            "MainCameraMP": fnum(row.get("MainCameraMP"), float),
            "OS": row.get("OS"),
            "Weight_g": fnum(row.get("Weight_g"), float),
            "NotableFeatures": row.get("NotableFeatures"),
            "ImageLocal": phone_local,
            "ImageURL": image_url,
            "BrandLogo": brand_logo,
            "Pros": pros,
            "Cons": cons,
        }

        # >>> attach live offer, if available
        try:
            offer = best_offer_for_slug(slug)
            if offer:
                item["LiveOffer"] = offer
        except Exception as _e:
            print("[offers] attach failed:", _e)

        # >>> attach human-friendly explanations (tooltips)
        try:
            item["Explain"] = attach_explanations(intent, row, pros, cons)
        except Exception as _e:
            print("[explain] failed:", _e)

        picks.append(item)

        # --- Merge YouTube review signals (if present) ---
        try:
            yt_pros, yt_cons = _load_youtube_signals(slug)
            # extend, but avoid duplicates; then trim to a reasonable count
            def _merge(a, b, limit):
                out, seen = [], set()
                for x in (a or []) + (b or []):
                    s = (x or "").strip()
                    if not s: 
                        continue
                    if s not in seen:
                        seen.add(s); out.append(s)
                    if len(out) >= limit:
                        break
                return out
            pros = _merge(pros, yt_pros, 5)
            cons = _merge(cons, yt_cons, 4)
        except Exception as _e:
            print("[yt-merge] failed:", _e)

    return picks

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
                ["ReleaseYear", "PriceUSD"], ascending=[False, True], na_position="last"
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

        # blurb
        ask = None
        if picks:
            try:
                if not df_cand.empty:
                    ask = _blurb_for_row(intent, df_cand.iloc[0]) or None
            except Exception as e:
                print("[_compose_blurb] failed:", e)
                ask = None
            if not ask:
                top = picks[0]
                ask = f"I’d start with {top['Brand']} {top['Model']} — strong match for what you asked."

        return ask, picks, int(count)

    except Exception as e:
        print("[_answer_or_ask] fatal:", e)
        df_top = _strict_budget_df(
            safe_df().sort_values(["ReleaseYear", "PriceUSD"], ascending=[False, True], na_position="last"),
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
        base = base.sort_values(["ReleaseYear","PriceUSD"], ascending=[False, True], na_position="last")
        d = base.head(30)

    ranked = unique_topn(rank_df(d, intent), 3)
    picks = _build_picks(ranked, intent)

    return (llm_blurb(intent, ranked.iloc[0]) or "Here’s what I recommend.", picks, int(len(d)))

# ---------- chat/message ----------

_RATE = {}  # ip -> [timestamps]


def allow(ip: str | None, limit: int = 30, window: int = 60) -> bool:
    """Simple sliding-window rate limiter keyed by IP (None-safe)."""
    key = ip or "unknown"
    now = time()
    rec = [t for t in _RATE.get(key, []) if now - t < window]
    rec.append(now)
    _RATE[key] = rec
    return len(rec) <= limit


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

        # ---- ultra-early budget catch: plain "700" / "$700" / "700 dollars"
        m_budget = re.fullmatch(r"\s*(\d{2,5})(?:\s*(?:usd|dollars|\$))?\s*$", text, re.I)
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


