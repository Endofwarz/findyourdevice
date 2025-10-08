# tools/make_brand_placeholders.py
import os
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

CSV = "data/processed/phones_clean.csv"
OUT_DIR = "frontend/public/brands"

def safe_font(size=48):
    try:
        # Use a common font if available
        return ImageFont.truetype("arial.ttf", size)
    except:
        return ImageFont.load_default()

def mk_logo(brand: str, path: str):
    W, H = 640, 320
    img = Image.new("RGB", (W, H), (245, 247, 255))
    d = ImageDraw.Draw(img)
    font = safe_font(56)

    # Brand text centered
    txt = brand
    tw, th = d.textbbox((0,0), txt, font=font)[2:]
    x = (W - tw) // 2
    y = (H - th) // 2
    # Soft rounded box behind text
    pad = 20
    d.rounded_rectangle([x - pad, y - pad, x + tw + pad, y + th + pad], radius=24, fill=(226, 232, 255))
    d.text((x, y), txt, fill=(45, 55, 72), font=font)
    img.save(path, "PNG", optimize=True)

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    df = pd.read_csv(CSV, low_memory=False)
    brands = sorted({str(b).strip() for b in df.get("Brand", []) if pd.notna(b) and str(b).strip()})
    for b in brands:
        fn = b.lower().replace(" ", "_")
        out = os.path.join(OUT_DIR, f"{fn}.png")
        if not os.path.exists(out):
            mk_logo(b, out)
            print("Wrote", out)
    print("Done. Logos in", OUT_DIR)

if __name__ == "__main__":
    main()
