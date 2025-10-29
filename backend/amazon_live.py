# backend/amazon_live.py
from __future__ import annotations
import os, time, hmac, hashlib, base64, urllib.parse, requests
from typing import Optional

# Pull creds from env
AWS_ACCESS_KEY = os.getenv("AMZ_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AMZ_SECRET_KEY")
PARTNER_TAG    = os.getenv("AMZ_PARTNER_TAG")
REGION         = os.getenv("AMZ_REGION", "eu-west-1")
HOST           = os.getenv("AMZ_HOST", "webservices.amazon.de")

# API endpoint
ENDPOINT = f"https://{HOST}/paapi5/searchitems"

# Basic headers
HEADERS = {"Content-Type": "application/json; charset=UTF-8", "Host": HOST}

def _aws_sign(payload: str, service="ProductAdvertisingAPI") -> dict[str, str]:
    """
    Build AWS Signature v4 headers for PA-API.
    """
    method, content_type = "POST", "application/json; charset=UTF-8"
    amz_target = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems"
    t = time.gmtime()
    amz_date = time.strftime("%Y%m%dT%H%M%SZ", t)
    date_stamp = time.strftime("%Y%m%d", t)

    canonical_uri = "/paapi5/searchitems"
    canonical_headers = f"content-type:{content_type}\nhost:{HOST}\nx-amz-date:{amz_date}\n"
    signed_headers = "content-type;host;x-amz-date"
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = (
        f"{method}\n{canonical_uri}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = f"{date_stamp}/{REGION}/{service}/aws4_request"
    string_to_sign = (
        f"{algorithm}\n{amz_date}\n{credential_scope}\n"
        + hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    )

    def sign(key, msg):
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k_date = sign(("AWS4" + AWS_SECRET_KEY).encode("utf-8"), date_stamp)
    k_region = sign(k_date, REGION)
    k_service = sign(k_region, service)
    k_signing = sign(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    auth_header = (
        f"{algorithm} Credential={AWS_ACCESS_KEY}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {"x-amz-date": amz_date, "Authorization": auth_header}

def fetch_amazon_offer(brand: str, model: str) -> Optional[dict]:
    """
    Search Amazon for the device, return best price & affiliate link.
    """
    if not (AWS_ACCESS_KEY and AWS_SECRET_KEY and PARTNER_TAG):
        print("[amazon] missing credentials")
        return None

    query = f"{brand} {model}"
    body = {
        "Keywords": query,
        "SearchIndex": "Electronics",
        "PartnerTag": PARTNER_TAG,
        "PartnerType": "Associates",
        "Resources": [
            "Images.Primary.Medium",
            "ItemInfo.Title",
            "Offers.Listings.Price",
            "Offers.Listings.Promotions",
        ],
    }
    payload = json_payload = __import__("json").dumps(body)
    signed = _aws_sign(payload)

    headers = HEADERS.copy()
    headers.update(signed)

    try:
        resp = requests.post(ENDPOINT, headers=headers, data=payload, timeout=10)
        resp.raise_for_status()
        js = resp.json()
    except Exception as e:
        print(f"[amazon] request failed: {e}")
        return None

    try:
        items = js.get("SearchResult", {}).get("Items", [])
        for it in items:
            title = it.get("ItemInfo", {}).get("Title", {}).get("DisplayValue", "")
            offer = (
                it.get("Offers", {})
                .get("Listings", [{}])[0]
                .get("Price", {})
                .get("DisplayAmount")
            )
            url = it.get("DetailPageURL")
            if offer and url:
                # Example "EUR 1,199.00" → float
                val = float("".join(c for c in offer if c.isdigit() or c in ",.").replace(",", "."))
                return {
                    "vendor": "Amazon",
                    "price": val,
                    "currency": "EUR",
                    "title": title,
                    "url": url,
                }
    except Exception as e:
        print(f"[amazon] parse failed: {e}")

    return None
