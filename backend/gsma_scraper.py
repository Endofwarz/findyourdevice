# backend/gsma_scraper.py
from __future__ import annotations
import re, requests
from bs4 import BeautifulSoup
PRICE_RE = re.compile(r"(?:about|around)?\s*([€$£])\s?([0-9][0-9.,]*)", re.I)
import re
import time
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup


def fetch_price_live(brand: str, model: str) -> dict | None:
    """
    Returns {"currency": "EUR"/"USD"/"GBP", "amount": float} when found on GSMArena.
    Looks in the 'Price' / 'Prices' field on the phone's page.
    """
    try:
        url = find_model_url(brand, model)  # you already have find_* helpers; reuse the one that builds the model URL
        if not url:
            return None
        html = requests.get(url, timeout=12).text
        soup = BeautifulSoup(html, "html.parser")

        # try Price row
        price_text = None
        for tr in soup.select("table#specs-list tr"):
            th = (tr.find("th") or {}).get_text(" ", strip=True).lower()
            if th in ("price", "prices"):
                price_text = (tr.find("td") or {}).get_text(" ", strip=True)
                break
        if not price_text:
            return None

        m = PRICE_RE.search(price_text)
        if not m:
            return None
        sym, num = m.group(1), m.group(2)
        amt = float(num.replace(",", "").replace(" ", ""))
        ccy = {"€": "EUR", "$": "USD", "£": "GBP"}.get(sym, "EUR")
        return {"currency": ccy, "amount": amt}
    except Exception:
        return None

def fetch_gallery_urls(brand: str, model: str, max_images: int = 6) -> list[str]:
    """
    Returns a list of full-size image URLs from GSMArena gallery if available.
    """
    urls = []
    try:
        page = find_model_url(brand, model)
        if not page:
            return urls
        html = requests.get(page, timeout=12).text
        soup = BeautifulSoup(html, "html.parser")

        # Big picture urls are usually in <img src="https://fdn2.gsmarena.com/vv/bigpic/....jpg">
        for img in soup.select("img"):
            src = img.get("src") or ""
            if "gsmarena.com/vv/bigpic/" in src:
                urls.append(src)
        # de-dup & cap
        out, seen = [], set()
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
                if len(out) >= max_images:
                    break
        return out
    except Exception:
        return []

# ---------- Constants / Globals ----------

BASE = "https://www.gsmarena.com"

# Use lxml if available, otherwise built-in html.parser (no external deps required)
try:
    import lxml  # noqa: F401
    _BS_PARSER = "lxml"
except Exception:
    _BS_PARSER = "html.parser"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit(537.36) (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------- Errors ----------

class ScrapeError(RuntimeError):
    """Raised on expected scraping errors (network/structure)."""
    pass


# ---------- HTTP helpers ----------

def _client() -> httpx.Client:
    return httpx.Client(
        headers=_HEADERS,
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


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, _BS_PARSER)


# ---------- Parsing helpers ----------

def _brand_listing_url(brand: str) -> str:
    html = _get_html(f"{BASE}/makers.php3")
    soup = _soup(html)
    for a in soup.select("a[href*='-phones-']"):
        name = (a.get_text() or "").strip().lower()
        href = (a.get("href") or "").strip()
        if brand.lower() in name and href.endswith(".php"):
            return f"{BASE}/{href}"
    raise ValueError(f"Brand not found: {brand}")

def _search_phone_url(brand: str, model: str) -> str | None:
    # GSMA search: res.php3?sSearch=...
    q = f"{brand} {model}".strip()
    html = _get_html(f"{BASE}/res.php3?sSearch={requests.utils.quote(q)}")
    soup = _soup(html)
    for a in soup.select("div.makers a[href*='.php']"):
        href = (a.get("href") or "").strip()
        title = (a.get_text(" ") or "").strip().lower()
        if brand.lower() in title and model.lower() in title:
            return f"{BASE}/{href}"
    # accept first reasonable hit if exact not found
    a = soup.select_one("div.makers a[href*='.php']")
    if a:
        return f"{BASE}/{a.get('href').strip()}"
    return None

def _find_phone_page(brand: str, model: str) -> str | None:
    # 1) try brand listing
    try:
        brand_url = _brand_url(brand)
        html = _get_html(brand_url)
        soup = _soup(html)
        for a in soup.select("div.makers a[href*='.php']"):
            title = (a.get_text(" ") or "").strip().lower()
            href = (a.get("href") or "").strip()
            if model.lower() in title:
                return f"{BASE}/{href}"
    except Exception:
        pass
    # 2) fallback to site search
    return _search_phone_url(brand, model)

def _parse_phone_cards(listing_html: str) -> List[Dict[str, str]]:
    """
    Brand page cards: <div class="makers"><ul><li><a href="apple_iphone_15_pro_max-12548.php">...</a></li>...</ul></div>
    Returns [{title, detail_url}, ...]
    """
    soup = _soup(listing_html)
    out: List[Dict[str, str]] = []
    for li in soup.select("div.makers ul li"):
        a = li.find("a")
        if not a:
            continue
        href = (a.get("href") or "").strip()
        title = (a.get_text(" ") or "").strip()
        if not href or not title:
            continue
        out.append({
            "title": title,
            "detail_url": f"{BASE}/{href}",
        })
    return out


def _parse_year_from_specs_page(detail_html: str) -> Optional[int]:
    """
    Look for "Released 2024, ..." or "Announced 2023, ..." anywhere in the text.
    """
    soup = _soup(detail_html)
    text = soup.get_text(" ", strip=True)
    m = re.search(r"(Released|Announced)\s+(\d{4})", text, re.I)
    if m:
        try:
            return int(m.group(2))
        except Exception:
            return None
    return None


def _td_value_by_label(soup: BeautifulSoup, label: str) -> Optional[str]:
    """
    GSMA tables are often <tr><td>Label</td><td>Value</td></tr>.
    Find a td whose string matches label (case-insensitive) and return the next td's text.
    """
    el = soup.find("td", string=re.compile(rf"^{re.escape(label)}$", re.I))
    if el:
        nxt = el.find_next("td")
        if nxt:
            return nxt.get_text(" ", strip=True)
    return None


def _parse_specs_from_specs_page(detail_html: str) -> Dict[str, object]:
    """
    Extract a conservative subset: OS, DisplayInches, Battery_mAh, RAM_GB, Storage_GB, MainCameraMP.
    """
    soup = _soup(detail_html)
    specs: Dict[str, object] = {
        "OS": "",
        "DisplayInches": None,
        "Battery_mAh": None,
        "RAM_GB": None,
        "Storage_GB": None,
        "MainCameraMP": None,
    }

    # OS
    os_val = _td_value_by_label(soup, "OS")
    if os_val:
        specs["OS"] = os_val

    # Display: from "Size" row (e.g., "6.7 inches, 110.2 cm2")
    size_val = _td_value_by_label(soup, "Size")
    if size_val:
        m = re.search(r"(\d+(?:\.\d+)?)\s*inches", size_val, re.I)
        if m:
            try:
                specs["DisplayInches"] = float(m.group(1))
            except Exception:
                pass

    # Battery: from "Battery" row (e.g., "5000 mAh, non-removable")
    bat_val = _td_value_by_label(soup, "Battery")
    if bat_val:
        m = re.search(r"(\d{3,5})\s*mAh", bat_val, re.I)
        if m:
            try:
                specs["Battery_mAh"] = int(m.group(1))
            except Exception:
                pass

    # Memory: from "Internal" row (e.g., "128GB 8GB RAM, 256GB 12GB RAM, ...")
    mem_val = _td_value_by_label(soup, "Internal")
    if mem_val:
        m = re.search(r"(\d{1,2})\s*GB\s*RAM", mem_val, re.I)
        if m:
            try:
                specs["RAM_GB"] = float(m.group(1))
            except Exception:
                pass
        nums = [int(x) for x in re.findall(r"(\d{2,4})\s*GB(?!\s*RAM)", mem_val, re.I)]
        if nums:
            specs["Storage_GB"] = float(max(nums))

    # Camera MP: try a few possible labels
    for cam_label in ["Triple", "Quad", "Dual", "Single", "Main Camera"]:
        cam_val = _td_value_by_label(soup, cam_label)
        if cam_val:
            m = re.search(r"(\d{2,3})\s*MP", cam_val, re.I)
            if m:
                try:
                    specs["MainCameraMP"] = float(m.group(1))
                    break
                except Exception:
                    pass

    return specs


# ---------- Public API: live specs for a single model ----------

def fetch_specs_live(brand: str, model: str) -> Dict[str, object]:
    """
    Live-only: find the brand page, choose the best-matching model link,
    and scrape a small set of specs.

    Returns {} on failure.
    Keys returned (when found): OS, DisplayInches, Battery_mAh, RAM_GB, Storage_GB, MainCameraMP, ReleaseYear.
    """
    try:
        brand_url = _brand_listing_url(brand)
        listing_html = _get_html(brand_url)
        cards = _parse_phone_cards(listing_html)
        if not cards:
            return {}

        want = f"{brand} {model}".strip().lower()

        def score_card(title: str) -> int:
            t = (title or "").lower()
            # simple token overlap + bonus for substring match
            overlap = len(set(want.split()) & set(t.split()))
            if want in t:
                overlap += 10
            return overlap

        best = max(cards, key=lambda c: score_card(c.get("title", "")), default=None)
        if not best:
            return {}

        detail_html = _get_html(best["detail_url"])
        specs = _parse_specs_from_specs_page(detail_html)
        year = _parse_year_from_specs_page(detail_html)
        if year:
            specs["ReleaseYear"] = year
        # MSRP not reliably present on GSMArena; keep pricing out
        return specs
    except Exception as e:
        print(f"[gsma-live] fetch_specs_live failed for {brand} {model}: {e}")
        return {}


# ---------- Optional: batch-by-brand (kept for compatibility) ----------

def fetch_brand_since(brand: str, min_year: int = 2023, max_items: int = 150) -> List[Dict[str, object]]:
    """
    Compatibility helper (used by old endpoints). Returns a list of rows for a brand
    since min_year. This DOES NOT write files; callers decide what to do with rows.
    """
    out: List[Dict[str, object]] = []
    try:
        brand_url = _brand_listing_url(brand)
        listing_html = _get_html(brand_url)
        cards = _parse_phone_cards(listing_html)
        if not cards:
            return out

        for card in cards:
            try:
                detail_html = _get_html(card["detail_url"])
                year = _parse_year_from_specs_page(detail_html) or 0
                if year and year < int(min_year):
                    continue

                specs = _parse_specs_from_specs_page(detail_html)

                title = (card.get("title") or "").strip()
                # Some titles are like "Apple iPhone 15 Pro". If it starts with brand, strip.
                model = title
                low_b = brand.strip().lower()
                if title.lower().startswith(low_b):
                    model = title[len(brand):].strip(" -")

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
                    "SourceFiles": card.get("detail_url"),
                }
                out.append(row)
                if len(out) >= max_items:
                    break

                time.sleep(0.2)  # be polite
            except ScrapeError:
                # skip one model, continue brand
                continue
            except Exception as e:
                print(f"[gsma] model parse error: {card.get('detail_url')} ({e})")
                continue

        return out
    except Exception as e:
        print(f"[gsma] brand fetch failed: {brand} ({e})")
        return []


def bootstrap_import(out_path: str, brands_csv: str, min_year: int = 2023) -> None:
    """
    Legacy helper kept for API compatibility. Collects rows with fetch_brand_since and
    writes CSV to out_path. You won't use this on Render free tier (no disk), but
    leaving it here avoids import errors if your code references it.
    """
    try:
        import os
        import csv
        import pandas as pd

        brands = [x.strip() for x in (brands_csv or "").split(",") if x.strip()]
        frames = []
        for b in brands:
            rows = fetch_brand_since(b, min_year=min_year)
            if rows:
                frames.append(pd.DataFrame(rows))
                time.sleep(0.4)

        if not frames:
            # still create an empty CSV with expected columns
            cols = ["Brand","Model","ReleaseYear","OS","DisplayInches","Battery_mAh",
                    "RAM_GB","Storage_GB","MainCameraMP","SourceFiles"]
            pd.DataFrame(columns=cols).to_csv(out_path, index=False)
            print(f"[gsma] wrote {out_path} rows=0")
            return

        all_df = pd.concat(frames, ignore_index=True)
        # best-effort de-dup by Brand+Model
        all_df.drop_duplicates(subset=["Brand","Model"], keep="last", inplace=True)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        all_df.to_csv(out_path, index=False)
        print(f"[gsma] wrote {out_path} rows={len(all_df)}")
    except Exception as e:
        print(f"[gsma] bootstrap_import failed: {e}")
