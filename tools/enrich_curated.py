# tools/enrich_curated.py
import base64, io, json, math, os
from PIL import Image, ImageDraw, ImageFont, ImageColor
import pandas as pd

IN_CSV  = "data/processed/phones_clean.csv"     # change if you use a curated CSV
OUT_CSV = "data/processed/phones_enriched.csv"
OUT_JSON= "data/processed/phones_enriched.json"

# brand price multipliers (coarse)
BRAND_FACTOR = {
    "Apple": 1.35, "Samsung": 1.20, "Google": 1.15, "OnePlus": 1.05,
    "Sony": 1.15, "Xiaomi": 0.95, "Motorola": 0.9, "Nothing": 1.0,
    "Asus": 1.05, "Oppo": 0.95, "Vivo": 0.95, "Realme": 0.9,
    "Honor": 0.95, "Huawei": 1.0, "Nokia": 0.85, "Lenovo": 0.85,
    "Tecno": 0.8, "Infinix": 0.8, "ZTE": 0.85, "Meizu": 0.9,
    "LG": 0.9, "HTC": 0.95, "Micromax": 0.75, "BLU": 0.75
}

def price_estimate(row):
    year = row.get("ReleaseYear") or 2022
    brand = str(row.get("Brand") or "").title()
    ram = float(row.get("RAM_GB") or 4)
    storage = float(row.get("Storage_GB") or 64)
    battery = float(row.get("Battery_mAh") or 4000)
    cam = float(row.get("MainCameraMP") or 12)

    # base by year (USD)
    base = 350
    if year >= 2025: base = 600
    elif year == 2024: base = 550
    elif year == 2023: base = 500

    # spec lift
    base += max(0, (ram - 6)) * 18
    base += max(0, (storage - 128)) * 1.2
    base += max(0, (battery - 4500)) * 0.05
    base += max(0, (cam - 48)) * 2.0

    # brand factor
    base *= BRAND_FACTOR.get(brand, 1.0)

    # round & clamp
    base = max(120, min(base, 1600))
    return round(base, -1)  # nearest $10

def gradient_image_data_url(text, w=512, h=320, a="#111827", b="#1f2937"):
    # Create a simple vertical gradient and overlay a label (Brand + Model)
    img = Image.new("RGB", (w, h), a)
    draw = ImageDraw.Draw(img)

    a_rgb = ImageColor.getrgb(a)
    b_rgb = ImageColor.getrgb(b)

    for y in range(h):
        t = y / (h - 1)
        r = int(a_rgb[0] + (b_rgb[0] - a_rgb[0]) * t)
        g = int(a_rgb[1] + (b_rgb[1] - a_rgb[1]) * t)
        bl = int(a_rgb[2] + (b_rgb[2] - a_rgb[2]) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, bl))

    # Font (try a few common ones, fallback to default)
    font = None
    for name in ["arial.ttf", "DejaVuSans.ttf", "SegoeUI.ttf"]:
        try:
            font = ImageFont.truetype(name, 28)
            break
        except Exception:
            pass
    if font is None:
        font = ImageFont.load_default()

    # Measure text with textbbox (Pillow 10+)
    bbox = draw.textbbox((0, 0), text, font=font)  # (left, top, right, bottom)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    # Draw centered
    draw.text(((w - tw) // 2, (h - th) // 2), text, fill="white", font=font)

    # Encode to data URL
    import io, base64
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"

def main():
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    df = pd.read_csv(IN_CSV)
    # normalize columns used
    for c in ["Brand","Model","ReleaseYear","PriceUSD","DisplayInches","Battery_mAh","RAM_GB","Storage_GB","MainCameraMP","OS","NotableFeatures","Slug"]:
        if c not in df.columns:
            df[c] = None

    # fill/improve price + create image url if missing
    prices = []
    images = []
    for _, row in df.iterrows():
        price = row.get("PriceUSD")
        if pd.isna(price) or float(price) < 120 or float(price) > 2000:
            price = price_estimate(row)
        else:
            price = float(price)

        # “photo” – a text-based placeholder: Brand + Model
        label = f"{row.get('Brand','')[:12]} {row.get('Model','')[:18]}".strip()
        imgurl = gradient_image_data_url(label or "Phone")

        prices.append(price)
        images.append(imgurl)

    df["PriceUSD"] = prices
    df["ImageURL"] = images

    df.to_csv(OUT_CSV, index=False)
    df.to_json(OUT_JSON, orient="records", force_ascii=False)
    print(f"✅ Wrote {len(df)} rows to:\n - {OUT_CSV}\n - {OUT_JSON}")

if __name__ == "__main__":
    main()
