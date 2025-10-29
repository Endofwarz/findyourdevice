# backend/amazon_live.py
from __future__ import annotations
import os, time, hmac, hashlib, base64, json, requests
from typing import Optional

# ----- EU host for ALL EU marketplaces (incl. Sweden) -----
AMZ_HOST         = os.getenv("AMZ_HOST", "webservices.amazon.co.uk")  # <— was .se (404)
AMZ_REGION       = os.getenv("AMZ_REGION", "eu-west-1")
AMZ_SERVICE      = "ProductAdvertisingAPI"
AMZ_MARKETPLACE  = os.getenv("AMZ_MARKETPLACE", "www.amazon.se")      # keep SE marketplace
AMZ_PARTNER_TAG  = os.getenv("AMZ_PARTNER_TAG", "").strip()           # your se tag, e.g. xxx-21
AMZ_ACCESS_KEY   = os.getenv("AMZ_ACCESS_KEY", "")
AMZ_SECRET_KEY   = os.getenv("AMZ_SECRET_KEY", "")

EUR_PER_SEK = float(os.getenv("FX_EUR_PER_SEK", "0.089"))  # tweak in env if you like

# offers/amazon.py
import os, logging
logger = logging.getLogger("offers")

def amazon_enabled():
    return all([
        os.getenv("AMAZON_PARTNER_TAG"),
        os.getenv("AMAZON_ACCESS_KEY"),
        os.getenv("AMAZON_SECRET_KEY"),
        os.getenv("AMAZON_HOST"),     # e.g. webservices.amazon.co.uk or .de
        os.getenv("AMAZON_REGION"),   # e.g. eu-west-1
    ])

def find_amazon_offer(query):
    if not amazon_enabled():
        logger.info("[amazon] disabled; missing credentials")
        return None
    try:
        # ... your PA-API request using the configured host/region/keys
        pass
    except Exception as e:
        logger.warning(f"[amazon] request failed: {e}")
        return None


def _sek_to_eur(v):
    try:
        return round(float(v) * EUR_PER_SEK, 2)
    except Exception:
        return None

def _signed_headers(payload: dict) -> dict:
    # PA-API 5 signing (short version)
    amz_target = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems"
    j = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    t = time.gmtime()
    amz_date = time.strftime("%Y%m%dT%H%M%SZ", t)
    datestamp = time.strftime("%Y%m%d", t)

    host = AMZ_HOST
    canonical_uri = "/paapi5/searchitems"
    canonical_query = ""
    canonical_headers = f"content-encoding:amz-1.0\ncontent-type:application/json; charset=utf-8\nhost:{host}\nx-amz-date:{amz_date}\nx-amz-target:{amz_target}\n"
    signed_headers = "content-encoding;content-type;host;x-amz-date;x-amz-target"
    payload_hash = hashlib.sha256(j.encode("utf-8")).hexdigest()
    canonical_request = f"POST\n{canonical_uri}\n{canonical_query}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{datestamp}/{AMZ_REGION}/{AMZ_SERVICE}/aws4_request"
    string_to_sign = f"{algorithm}\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"

    def _hmac(key, msg): return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()
    k_date  = _hmac(("AWS4" + AMZ_SECRET_KEY).encode("utf-8"), datestamp)
    k_reg   = hmac.new(k_date, AMZ_REGION.encode("utf-8"), hashlib.sha256).digest()
    k_svc   = hmac.new(k_reg, AMZ_SERVICE.encode("utf-8"), hashlib.sha256).digest()
    k_sign  = hmac.new(k_svc, b"aws4_request", hashlib.sha256).digest()
    signature = hmac.new(k_sign, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    return {
        "content-encoding": "amz-1.0",
        "content-type": "application/json; charset=utf-8",
        "host": host,
        "x-amz-date": amz_date,
        "x-amz-target": amz_target,
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={AMZ_ACCESS_KEY}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
    }

def fetch_amazon_offer(brand: str, model: str) -> Optional[dict]:
    """Return {url, price, currency} in EUR if available, else None."""
    if not (AMZ_ACCESS_KEY and AMZ_SECRET_KEY and AMZ_PARTNER_TAG):
        return None

    q = f"{brand} {model}"
    payload = {
        "PartnerTag": AMZ_PARTNER_TAG,
        "PartnerType": "Associates",
        "Marketplace": AMZ_MARKETPLACE,
        "ItemCount": 3,
        "Keywords": q,
        "Resources": [
            "ItemInfo.Title",
            "Offers.Listings.Price",
            "Offers.Listings.Availability.MaxOrderQuantity",
            "DetailPageURL",
        ],
        "SearchIndex": "All",
    }

    url = f"https://{AMZ_HOST}/paapi5/searchitems"
    try:
        r = requests.post(url, headers=_signed_headers(payload), data=json.dumps(payload), timeout=12)
        # PA-API returns 200 with Errors block; treat non-200 as failure for clarity
        r.raise_for_status()
        j = r.json()
    except Exception as e:
        print("[amazon] request failed:", e)
        return None

    items = (j.get("SearchResult") or {}).get("Items") or []
    for it in items:
        offers = (it.get("Offers") or {}).get("Listings") or []
        if not offers:
            continue
        price = (offers[0].get("Price") or {})
        amount = price.get("Amount")
        currency = price.get("Currency") or "SEK"
        if amount is None:
            continue
        # Convert SEK→EUR for consistency in frontend
        out_price = _sek_to_eur(amount) if currency.upper() == "SEK" else float(amount)
        out_curr  = "EUR" if currency.upper() == "SEK" else currency
        return {
            "url": it.get("DetailPageURL"),
            "price": out_price,
            "currency": out_curr,
            "raw_currency": currency,
        }
    return None
