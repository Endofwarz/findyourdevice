# amazon_live.py
import os, time, hmac, hashlib, base64, json, requests
from datetime import datetime

# --- Config (Sweden) ---
AMZ_ACCESS_KEY = os.getenv("AMZ_ACCESS_KEY", "")
AMZ_SECRET_KEY = os.getenv("AMZ_SECRET_KEY", "")
AMZ_PARTNER_TAG = os.getenv("AMZ_PARTNER_TAG", "")   # your amazon.se tracking ID
AMZ_HOST = os.getenv("AMZ_HOST", "webservices.amazon.se")
AMZ_REGION = os.getenv("AMZ_REGION", "eu-west-1")
AMZ_MARKETPLACE = os.getenv("AMZ_MARKETPLACE", "www.amazon.se")
AMZ_LANGUAGE = os.getenv("AMZ_LANGUAGE", "sv_SE")

# simple FX so we can show EUR while querying amazon.se
EUR_PER_SEK = float(os.getenv("FX_EUR_PER_SEK", "0.089"))  # ~example; set your preferred rate

def _aws4_sign(key, date_stamp, region_name, service_name, string_to_sign):
    k_date = hmac.new(("AWS4" + key).encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256).digest()
    k_region = hmac.new(k_date, region_name.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, service_name.encode("utf-8"), hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return signature

def _signed_headers(payload: str, host: str, region: str):
    service = "ProductAdvertisingAPI"
    amz_target = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems"
    t = datetime.utcnow()
    amz_date = t.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = t.strftime("%Y%m%d")

    canonical_uri = "/paapi5/searchitems"
    canonical_querystring = ""
    canonical_headers = f"content-encoding:\nhost:{host}\nx-amz-date:{amz_date}\n"
    signed_headers = "content-encoding;host;x-amz-date"
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = f"POST\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = f"{algorithm}\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"

    signature = _aws4_sign(AMZ_SECRET_KEY, date_stamp, region, service, string_to_sign)
    auth_header = (
        f"{algorithm} Credential={AMZ_ACCESS_KEY}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    headers = {
        "content-encoding": "",
        "content-type": "application/json; charset=UTF-8",
        "host": host,
        "x-amz-date": amz_date,
        "authorization": auth_header,
    }
    return headers

def _convert_sek_to_eur(v):
    try:
        return round(float(v) * EUR_PER_SEK, 2)
    except Exception:
        return None

def fetch_amazon_offer(brand: str, model: str) -> dict | None:
    """Search amazon.se for the phone and return a minimal offer dict in EUR."""
    if not (AMZ_ACCESS_KEY and AMZ_SECRET_KEY and AMZ_PARTNER_TAG):
        return None

    host = AMZ_HOST
    endpoint = f"https://{host}/paapi5/searchitems"

    keywords = f"{brand} {model}".strip()
    body = {
        "Keywords": keywords,
        "ItemCount": 1,
        "ItemPage": 1,
        "PartnerTag": AMZ_PARTNER_TAG,
        "PartnerType": "Associates",
        "Marketplace": AMZ_MARKETPLACE,     # <- www.amazon.se
        "Resources": [
            "ItemInfo.Title",
            "Offers.Listings.Price",
            "Offers.Listings.Availability.MaxOrderQuantity",
            "Offers.Listings.IsBuyBoxWinner",
            "Offers.Listings.MerchantInfo",
            "Images.Primary.Medium"
        ],
    }
    if AMZ_LANGUAGE:
        body["LanguagesOfPreference"] = [AMZ_LANGUAGE]

    payload = json.dumps(body, ensure_ascii=False)
    headers = _signed_headers(payload, host, AMZ_REGION)

    try:
        r = requests.post(endpoint, headers=headers, data=payload, timeout=12)
        # 404s usually mean host/marketplace mismatch; this ensures we see the body
        if r.status_code >= 400:
            print("[amazon] http error:", r.status_code, r.text[:300])
            r.raise_for_status()
        j = r.json()
    except Exception as e:
        print("[amazon] request failed:", e)
        return None

    items = ((j.get("SearchResult") or {}).get("Items") or [])
    if not items:
        return None

    it = items[0]
    title = (((it.get("ItemInfo") or {}).get("Title") or {}).get("DisplayValue")) or ""
    url = it.get("DetailPageURL") or ""
    listings = ((it.get("Offers") or {}).get("Listings") or [])
    price = None
    currency = None
    if listings:
        p = ((listings[0].get("Price") or {}).get("Amount"))
        c = ((listings[0].get("Price") or {}).get("Currency"))
        if p:
            price = float(p)
            currency = c or "SEK"

    if not price:
        return None

    # convert to EUR so the rest of your system can assume EUR
    price_eur = _convert_sek_to_eur(price) if currency == "SEK" else price
    currency_out = "EUR" if currency == "SEK" else (currency or "EUR")

    return {
        "title": title,
        "url": url,
        "price": price_eur,
        "currency": currency_out,
        "raw_price": price,       # optional: keep raw for debugging
        "raw_currency": currency, # optional
        "image": (((it.get("Images") or {}).get("Primary") or {}).get("Medium") or {}).get("URL"),
    }
