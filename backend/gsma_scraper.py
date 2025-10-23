# gsma_scraper.py
from __future__ import annotations
import os, re, csv, time, json, pathlib
from typing import Dict, List, Tuple, Optional
import requests
from bs4 import BeautifulSoup
from datetime import datetime

BASE = "https://www.gsmarena.com"
DATA_RAW  = pathlib.Path("data/raw/gsma")
DATA_PROC = pathlib.Path("data/processed")
DATA_RAW.mkdir(parents=True, exist_ok=True)
DATA_PROC.mkdir(parents=True, exist_ok=True)

PHONES_CSV = os.getenv("PHONES_CSV", str(DATA_PROC / "phones_clean.csv"))

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"
)
SLOW = float(os.getenv("GSMA_DELAY", "0.8"))  # seconds between requests
TIMEOUT = 15

def _http(url: str, params=None) -> Optional[str]:
    try:
        r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        time.sleep(SLOW)
        return r.text
    except Exception as e:
        print("[gsma] http error:", e, url)
        return None

def _brand_slug(name: str) -> Optional[str]:
    """
    Map brand -> GSMArena brand page slug.
    Examples:
      Samsung -> samsung-phones-6.php
      Apple   -> apple-phones-48.php
    We discover via the main brands index and cache locally.
    """
    idx_path = DATA_RAW / "brands_index.html"
    html = idx_path.read_text("utf-8") if idx_path.exists() else _http(BASE + "/makers.php3")
    if not html: return None
    if not idx_path.exists():
        idx_path.write_text(html, "utf-8")

    soup = BeautifulSoup(html, "html.parser")
    for a in soup.select("div.st-text a"):
        label = (a.text or "").strip().lower()
        href = a.get("href") or ""
        if not href.endswith(".php"): 
            continue
        if name.strip().lower() == label:
            return href
    # fuzzy: try startswith
    low = name.strip().lower()
    for a in soup.select("div.st-text a"):
        label = (a.text or "").strip().lower()
        href = a.get("href") or ""
        if href.endswith(".php") and (low in label or label in low):
            return href
    return None

def _parse_year(text: str) -> Optional[int]:
    m = re.search(r"(20\d{2})", text or "")
    return int(m.group(1)) if m else None

def _clean_float(s: str) -> Optional[float]:
    try:
        s = (s or "").lower()
        s = s.replace(",", " ")
        # inches like "6.7 inches"
        m = re.search(r"(\d+(?:\.\d+)?)", s)
        return float(m.group(1)) if m else None
    except Exception:
        return None

def _clean_int(s: str) -> Optional[int]:
    try:
        m = re.search(r"(\d{2,5})", s or "")
        return int(m.group(1)) if m else None
    except Exception:
        return None

def _camera_mp(s: str) -> Optional[float]:
    # e.g., "50 MP", "64+12 MP", take the largest number
    nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*mp", (s or "").lower())]
    return max(nums) if nums else None

def _price_usd(s: str) -> Optional[float]:
    # GSMA often: "About 999 EUR" / "About 799 USD" / "€1,199"
    if not s: return None
    s = s.replace(",", "")
    m = re.search(r"(\d{2,5})(?:\s*(usd|\$))", s.lower())
    if m: return float(m.group(1))
    # EUR → rough USD conversion? avoid guessing; return None to keep your fallback
    return None

def _normalize_os(s: str) -> Optional[str]:
    if not s: return None
    t = s.lower()
    if "ios" in t: return "iOS"
    if "android" in t: return "Android"
    return None

def _slugify(brand: str, model: str) -> str:
    import re
    s = f"{brand}-{model}".lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s

def _load_csv() -> List[Dict]:
    if not pathlib.Path(PHONES_CSV).exists():
        return []
    with open(PHONES_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def _save_csv(rows: List[Dict]):
    cols = [
        "ID","Brand","Model","Slug","ReleaseYear","PriceUSD","DisplayInches",
        "Battery_mAh","RAM_GB","Storage_GB","MainCameraMP","OS","Weight_g",
        "NotableFeatures","SourceFiles"
    ]
    with open(PHONES_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})

def _upsert_rows(new_rows: List[Dict]):
    cur = _load_csv()
    by_slug = {r.get("Slug"): r for r in cur if r.get("Slug")}
    for r in new_rows:
        by_slug[r["Slug"]] = r
    out = list(by_slug.values())
    # simple stable ID: keep old IDs, assign new sequential IDs to inserts
    max_id = 0
    for r in out:
        try:
            max_id = max(max_id, int(r.get("ID") or 0))
        except: pass
    next_id = max_id + 1
    for r in out:
        if not r.get("ID"):
            r["ID"] = str(next_id); next_id += 1
    _save_csv(out)

def _parse_phone_specs(phone_url: str) -> Optional[Dict]:
    html = _http(phone_url)
    if not html: return None
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title = (soup.select_one("h1.specs-phone-name-title") or {}).get_text(strip=True) or ""
    brand = title.split()[0] if title else ""
    model = title[len(brand):].strip() if title else ""

    # Year (from "Launch" row where it often says "Announced 2024, Sep")
    launch = soup.find("td", text=re.compile(r"Announced", re.I))
    year = None
    if launch and launch.find_next("td"):
        year = _parse_year(launch.find_next("td").get_text(" ", strip=True))
    if not year:
        # fallback from breadcrumb (sometimes includes "(2024)")
        crumb = " ".join([a.get_text(" ", strip=True) for a in soup.select("div.breadcrumb a")])
        year = _parse_year(crumb)

    # Display diagonal
    disp_row = soup.find("td", text=re.compile(r"Display", re.I))
    display_inches = None
    if disp_row and disp_row.find_next("td"):
        display_inches = _clean_float(disp_row.find_next("td").get_text(" ", strip=True))

    # Battery
    bat_row = soup.find("td", text=re.compile(r"Battery", re.I))
    battery = None
    if bat_row and bat_row.find_next("td"):
        battery = _clean_int(bat_row.find_next("td").get_text(" ", strip=True))

    # RAM/Storage (from "Memory" section lines, try to pick the highest common variant)
    mem_row = soup.find("td", text=re.compile(r"Internal", re.I))
    ram_gb, storage_gb = None, None
    if mem_row and mem_row.find_next("td"):
        memtxt = mem_row.find_next("td").get_text(" ", strip=True).lower()
        # variants like "128GB 8GB RAM, 256GB 12GB RAM"
        rams = [int(x) for x in re.findall(r"(\d{1,2})\s*gb\s*ram", memtxt)]
        stgs = [int(x) for x in re.findall(r"(\d{2,4})\s*gb(?!\s*ram)", memtxt)]
        ram_gb = max(rams) if rams else None
        storage_gb = max(stgs) if stgs else None

    # Main camera MP (from "Main Camera")
    cam_row = soup.find("td", text=re.compile(r"Main\s*Camera", re.I))
    main_mp = None
    if cam_row and cam_row.find_next("td"):
        main_mp = _camera_mp(cam_row.find_next("td").get_text(" ", strip=True))

    # OS
    os_row = soup.find("td", text=re.compile(r"OS", re.I))
    os_name = None
    if os_row and os_row.find_next("td"):
        os_name = _normalize_os(os_row.find_next("td").get_text(" ", strip=True))

    # Weight
    w_row = soup.find("td", text=re.compile(r"Weight", re.I))
    weight_g = None
    if w_row and w_row.find_next("td"):
        wtxt = w_row.find_next("td").get_text(" ", strip=True)
        m = re.search(r"(\d{2,4})\s*g", wtxt.lower())
        weight_g = int(m.group(1)) if m else None

    # Notable features (quick pick from feature keywords visible on page)
    features = []
    full_text = soup.get_text(" ", strip=True).lower()
    if "ip68" in full_text: features.append("IP68")
    if "wireless charging" in full_text: features.append("wireless charging")
    if re.search(r"\b120hz\b|\b120 hz\b", full_text): features.append("120hz")
    if "esim" in full_text: features.append("eSIM")
    if "5g" in full_text: features.append("5g")
    features = sorted(set(features))

    # Price (indicative, USD only if explicitly stated)
    price_row = soup.find("td", text=re.compile(r"Price", re.I))
    price_usd = None
    if price_row and price_row.find_next("td"):
        price_usd = _price_usd(price_row.find_next("td").get_text(" ", strip=True))

    # Slug
    slug = _slugify(brand, model)

    return {
        "Brand": brand, "Model": model, "Slug": slug,
        "ReleaseYear": year,
        "PriceUSD": price_usd,  # may be None; your fallback logic will fill
        "DisplayInches": display_inches,
        "Battery_mAh": battery,
        "RAM_GB": ram_gb,
        "Storage_GB": storage_gb,
        "MainCameraMP": main_mp,
        "OS": os_name,
        "Weight_g": weight_g,
        "NotableFeatures": ", ".join(features),
        "SourceFiles": "gsma",
    }

def fetch_brand_since(brand_name: str, min_year: int = 2023, max_pages: int = 20) -> List[Dict]:
    """
    Crawl brand listing pages, filter by year >= min_year, then parse each phone page.
    """
    bslug = _brand_slug(brand_name)
    if not bslug:
        print(f"[gsma] brand not found: {brand_name}")
        return []

    url = f"{BASE}/{bslug}"
    all_rows: List[Dict] = []
    page = 1
    while page <= max_pages and url:
        html = _http(url)
        if not html: break
        soup = BeautifulSoup(html, "html.parser")

        # phone cards live under .makers li a
        for a in soup.select("div.makers ul li a"):
            href = a.get("href") or ""
            name = (a.get_text(" ", strip=True) or "").strip()
            # year is often in the small tag or name; we'll check on detail page anyway
            phone_url = f"{BASE}/{href}"
            specs = _parse_phone_specs(phone_url)
            if not specs: 
                continue
            if specs.get("ReleaseYear") and specs["ReleaseYear"] < min_year:
                continue
            if not specs.get("Brand") or not specs.get("Model"):
                continue
            all_rows.append(_to_csv_row(specs))

        # pagination: look for "Next" link
        nxt = soup.find("a", text=re.compile(r"Next", re.I))
        url = BASE + "/" + nxt.get("href") if nxt and nxt.get("href") else None
        page += 1

    if all_rows:
        _upsert_rows(all_rows)
    return all_rows

def _to_csv_row(s: Dict) -> Dict:
    # Align with your CSV schema
    return {
        "ID": "",  # assigned on upsert
        "Brand": s.get("Brand"),
        "Model": s.get("Model"),
        "Slug": s.get("Slug"),
        "ReleaseYear": s.get("ReleaseYear") or "",
        "PriceUSD": s.get("PriceUSD") or "",
        "DisplayInches": s.get("DisplayInches") or "",
        "Battery_mAh": s.get("Battery_mAh") or "",
        "RAM_GB": s.get("RAM_GB") or "",
        "Storage_GB": s.get("Storage_GB") or "",
        "MainCameraMP": s.get("MainCameraMP") or "",
        "OS": s.get("OS") or "",
        "Weight_g": s.get("Weight_g") or "",
        "NotableFeatures": s.get("NotableFeatures") or "",
        "SourceFiles": "gsma",
    }
