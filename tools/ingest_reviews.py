# tools/ingest_reviews.py
import csv, os, time, pathlib
from tools.sources.youtube import top_video_ids, transcript_text, summarize_to_pros_cons

OUT_DIR = pathlib.Path("data/processed")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_CSV = OUT_DIR / "reviews.csv"

# Start with a small, fixed list (popular models).
# Later we can generate this list from your specs table automatically.
SEED_MODELS = [
    ("Apple",  "iPhone 15"),
    ("Samsung","Galaxy S24"),
    ("Google", "Pixel 8"),
    ("OnePlus","12"),
    ("Xiaomi", "14"),
]

def slugify(s: str) -> str:
    import re
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")

def run_reviews():
    rows = []
    for brand, model in SEED_MODELS:
        query = f"{brand} {model} review"
        vids = top_video_ids(query, max_results=3)
        time.sleep(0.5)

        all_pros, all_cons = [], []
        for vid in vids:
            text = transcript_text(vid)
            if not text:
                continue
            pros, cons = summarize_to_pros_cons(text)
            all_pros.extend(pros)
            all_cons.extend(cons)
            time.sleep(0.4)

        # dedupe & trim
        def uniq_keep(seq, n):
            out, seen = [], set()
            for x in seq:
                if x not in seen:
                    seen.add(x); out.append(x)
                if len(out) >= n: break
            return out

        pros_final = uniq_keep(all_pros, 5)
        cons_final = uniq_keep(all_cons, 4)

        rows.append({
            "slug": slugify(f"{brand} {model}"),
            "pros": "|".join(pros_final),
            "cons": "|".join(cons_final),
            "source": "youtube",
        })

    # write CSV
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["slug","pros","cons","source"])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"[reviews] wrote {len(rows)} rows -> {OUT_CSV}")

if __name__ == "__main__":
    run_reviews()
