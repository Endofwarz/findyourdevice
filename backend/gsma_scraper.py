# backend/gsma_scraper.py
from __future__ import annotations
import os, re, time
from typing import List, Dict
import httpx
from bs4 import BeautifulSoup
import pandas as pd
import requests


# Prefer lxml if present, otherwise fall back to Python's built-in parser
try:
    import lxml  # noqa: F401
    _BS_PARSER = "lxml"
except Exception:
    _BS_PARSER = "html.parser"

_UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, _BS_PARSER)

def _get(url: str, **kwargs) -> requests.Response:
    # always send a browser-y UA; merge with any caller headers
    headers = dict(_UA_HEADERS)
    headers.update(kwargs.pop("headers", {}) or {})
    r = requests.get(url, headers=headers, timeout=kwargs.pop("timeout", 15), **kwargs)
    r.raise_for_status()
    return r


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

BASE = "https://www.gsmarena.com"

class ScrapeError(RuntimeError):
    pass

def _client():
    return httpx.Client(
        headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
        timeout=httpx.Timeout(12.0, connect=12.0),
        follow_redirects=True,
    )

def _get_html(url: str) -> str:
    try:
        with _client() as c:
            r = c.get(url)
            r.raise_for_status()
            return r.text
    except Exception as e:
        raise ScrapeError(f"fetch failed: {e}") from e

def _brand_listing_url(brand: str) -> str:
    # Example brand pages: /apple-phones-48.php, /samsung-phones-6.php, etc.
    # We search the brand directory page to resolve the brand id.
    html = _get_html(f"{BASE}/makers.php3")
    soup = BeautifulSoup(resp.text)
    for a in soup.select("table tr td a"):
        name = (a.get_text() or "").strip().lower()
        href = a.get("href") or ""
        if not href.endswith(".php"):
            continue
        if brand.strip().lower() in name:
            return f"{BASE}/{href}"
    raise ScrapeError(f"brand not found in makers list: {brand}")

def _parse_phone_cards(html: str) -> List[Dict]:
    soup = BeautifulSoup(resp.text)
    out = []
    for li in soup.select("div.makers ul li"):
        a = li.find("a")
        if not a: 
            continue
        href = a.get("href") or ""
        title = (a.get_text(" ") or "").strip()
        if not href or not title:
            continue
        out.append({
            "detail_url": f"{BASE}/{href}",
            "title": title,
        })
    return out

def _parse_year_from_specs_page(html: str) -> int | None:
    soup = BeautifulSoup(resp.text)
    # GSMArena shows "Released 2024, ..." or "Announced 2023, ..."
    text = soup.get_text(" ", strip=True)
    m = re.search(r"(Released|Announced)\s+(\d{4})", text, re.I)
    if m:
        try:
            return int(m.group(2))
        except Exception:
            return None
    return None

def _parse_specs_from_specs_page(html: str) -> Dict:
    soup = BeautifulSoup(resp.text)
    specs = {}
    # These selectors are robust enough for a first pass.
    def get_val(label: str):
        el = soup.find("td", text=re.compile(rf"^{re.escape(label)}$", re.I))
        if el and el.find_next("td"):
            return el.find_next("td").get_text(" ", strip=True)
        return None

    specs["DisplayInches"] = None
    disp = get_val("Size")
    if disp:
        m = re.search(r"(\d+\.\d+|\d+)\s*inches", disp, re.I)
        if m:
            specs["DisplayInches"] = float(m.group(1))

    specs["Battery_mAh"] = None
    bat = get_val("Battery")
    if bat:
        m = re.search(r"(\d{3,5})\s*mAh", bat, re.I)
        if m:
            specs["Battery_mAh"] = int(m.group(1))

    specs["RAM_GB"] = None
    mem = get_val("Internal")
    if mem:
        m = re.search(r"(\d{1,2})\s*GB\s*RAM", mem, re.I)
        if m:
            specs["RAM_GB"] = float(m.group(1))

    specs["Storage_GB"] = None
    if mem:
        # pick the largest storage figure listed
        nums = [int(x) for x in re.findall(r"(\d{2,4})\s*GB(?!\s*RAM)", mem, re.I)]
        if nums:
            specs["Storage_GB"] = float(max(nums))

    specs["MainCameraMP"] = None
    cam = get_val("Triple") or get_val("Dual") or get_val("Single") or get_val("Quad") or get_val("Main Camera")
    if cam:
        m = re.search(r"(\d{2,3})\s*MP", cam, re.I)
        if m:
            specs["MainCameraMP"] = float(m.group(1))

    specs["OS"] = get_val("OS") or ""
    return specs

def fetch_brand_since(brand: str, min_year: int = 2023, max_items: int = 150) -> list[dict]:
    """Return structured phone rows for a brand since min_year."""
    url = _brand_listing_url(brand)
    html = _get_html(url)
    cards = _parse_phone_cards(html)
    if not cards:
        raise ScrapeError("no models parsed on brand page")

    out = []
    for card in cards:
        try:
            detail = _get_html(card["detail_url"])
            year = _parse_year_from_specs_page(detail) or 0
            if year < int(min_year):
                continue
            specs = _parse_specs_from_specs_page(detail)
            # Basic fields
            name = (card["title"] or "").strip()
            # Split brand/model conservatively
            if name.lower().startswith(brand.lower()):
                model = name[len(brand):].strip(" -")
            else:
                model = name
            row = {
                "Brand": brand.title(),
                "Model": model,
                "ReleaseYear": year or None,
                "OS": specs.get("OS") or None,
                "DisplayInches": specs.get("DisplayInches"),
                "Battery_mAh": specs.get("Battery_mAh"),
                "RAM_GB": specs.get("RAM_GB"),
                "Storage_GB": specs.get("Storage_GB"),
                "MainCameraMP": specs.get("MainCameraMP"),
                "SourceFiles": card["detail_url"],
            }
            out.append(row)
            if len(out) >= max_items:
                break
            time.sleep(0.2)  # be polite
        except ScrapeError as e:
            # log and continue
            print(f"[gsma] skip {card.get('detail_url')}: {e}")
        except Exception as e:
            print(f"[gsma] parse error {card.get('detail_url')}: {e}")
    return out

EXPECTED_COLS = [
    "ID","Brand","Model","Slug","ReleaseYear","PriceUSD","DisplayInches",
    "Battery_mAh","RAM_GB","Storage_GB","MainCameraMP","OS","Weight_g",
    "NotableFeatures","SourceFiles"
]

def _dedupe_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if "Slug" in df.columns and df["Slug"].notna().any():
        return df.drop_duplicates(subset=["Slug"])
    return df.drop_duplicates(subset=["Brand","Model"])

def build_gsma_df(brands: list[str], min_year: int = 2023) -> pd.DataFrame:
    frames = []
    for b in brands:
        b = b.strip()
        if not b:
            continue
        try:
            part = fetch_brand_since(b, min_year=min_year)  # your scraper function
            if isinstance(part, pd.DataFrame) and not part.empty:
                frames.append(part)
            time.sleep(0.5)  # be nice to GSMArena
        except Exception as e:
            print("[gsma] brand failed:", b, e)
    if not frames:
        return pd.DataFrame(columns=EXPECTED_COLS)
    return _dedupe_df(pd.concat(frames, ignore_index=True))

def bootstrap_import(out_path: str, brands_csv: str, min_year: int = 2023):
    brands = [x.strip() for x in (brands_csv or "").split(",") if x.strip()]
    df = build_gsma_df(brands, min_year=min_year)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"[gsma] wrote {out_path} rows={len(df)}")
