import argparse, re, csv
from pathlib import Path
import pandas as pd
import numpy as np

SCHEMA = [
    "ID","Brand","Model","Slug","ReleaseYear","PriceUSD",
    "DisplayInches","Battery_mAh","RAM_GB","Storage_GB",
    "MainCameraMP","OS","Weight_g","NotableFeatures","SourceFiles"
]

SYN = {
    "brand":   ["brand","company","oem","maker","brand_name","manufacturer"],
    "model":   ["model","model_name","phone","device","device_name","name","title","variant"],
    "release": ["release_year","year","announced","launched","release","launch","release_date","year_released"],
    "price":   ["price_usd","price($)","price","launch_price","price_in_usd","mrp","price_us"],
    "display": ["display_inches","display_size","size(inches)","screen_size","display","screen"],
    "battery": ["battery_mah","battery capacity","battery","battery_capacity","capacity_mah","battery(mAh)","battery_maH"],
    "ram":     ["ram_gb","ram (gb)","ram","memory_ram","ram_size","ram_g","memory"],
    "storage": ["storage_gb","storage (gb)","storage","rom","internal_storage","memory_storage","storage_capacity"],
    "camera":  ["main_camera_mp","rear_camera_mp","camera_mp","camera","main camera","primary_camera","rear_camera"],
    "os":      ["os","operating_system","platform_os","software"],
    "weight":  ["weight_g","weight (g)","weight","mass_g","weight_gm"],
    "features":["features","notablefeatures","extras","special_features","other_features","key_features","additional_features"],
}

KNOWN_BRANDS = [
    "apple","samsung","xiaomi","google","huawei","oneplus","sony","motorola","nokia","oppo","vivo",
    "asus","realme","honor","zte","nothing","infinix","tecno","lenovo","meizu","tcl","sharp","lg","blackview","cat","doogee","nubia","redmagic","fairphone","ulefone","unihertz"
]

def col(df, keys):
    keys = [k.lower() for k in keys]
    m = {c.lower(): c for c in df.columns}
    for k in keys:
        if k in m: return m[k]
    for k in keys:
        for lc, orig in m.items():
            if lc.startswith(k): return orig
    return None

def sniff_sep(path: Path, default=","):
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            sample = f.read(4096)
        dialect = csv.Sniffer().sniff(sample, delimiters=[",",";","|","\t"])
        return dialect.delimiter
    except Exception:
        first_line = sample.splitlines()[0] if 'sample' in locals() and sample else ""
        if first_line.count(";") > first_line.count(","): return ";"
        return default

def read_csv_smart(p: Path):
    tries = []
    try:
        sep = sniff_sep(p)
        df = pd.read_csv(p, sep=sep, engine="python")
        return df, None
    except Exception as e:
        tries.append(f"sniff:{e}")
    try:
        df = pd.read_csv(p)
        return df, None
    except Exception as e:
        tries.append(f"default:{e}")
    try:
        df = pd.read_csv(p, engine="python", on_bad_lines="skip")
        return df, None
    except Exception as e:
        tries.append(f"python-skip:{e}")
    try:
        df = pd.read_csv(p, engine="python", on_bad_lines="skip", encoding="latin-1")
        return df, None
    except Exception as e:
        tries.append(f"latin1:{e}")
    return pd.DataFrame(), " | ".join(tries)

# ---------- PARSERS (robust) ----------
def parse_year(s):
    if pd.isna(s): return np.nan
    y = pd.to_numeric(s, errors="coerce")
    if not pd.isna(y) and 1995 <= y <= 2035: return int(y)
    m = re.search(r"(20\d{2})", str(s))
    return int(m.group(1)) if m else np.nan

def parse_inches(s):
    if s is None: return np.nan
    t = str(s).lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:inches|inch|\"|in\b)", t)
    if m: 
        v = float(m.group(1))
        return v if 3.0 <= v <= 8.5 else np.nan
    # fallbacks: pick a plausible number between 3–8.5 from all numbers
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    candidates = [x for x in nums if 3.0 <= x <= 8.5]
    return candidates[0] if candidates else np.nan

def parse_mah(s):
    if s is None: return np.nan
    t = str(s).lower()
    m = re.search(r"(\d{3,5})\s*m?ah", t)
    if m: return float(m.group(1))
    nums = [int(x) for x in re.findall(r"\d{3,5}", t)]
    # prefer values in typical range 1500–7000
    for x in nums:
        if 1500 <= x <= 10000: return float(x)
    return np.nan

def parse_ram_gb(s):
    if s is None: return np.nan
    t = str(s).lower()
    # patterns like "8/128"
    if "/" in t:
        parts = re.findall(r"\d+(?:\.\d+)?", t)
        if parts:
            n = float(parts[0])
            # unit detection
            if "mb" in t and "gb" not in t and n > 64: return round(n/1024, 1)
            return n
    if "tb" in t:
        m = re.search(r"(\d+(?:\.\d+)?)\s*tb", t)
        return float(m.group(1))*1024 if m else np.nan  # extremely rare for RAM, but safe
    if "gb" in t:
        m = re.search(r"(\d+(?:\.\d+)?)\s*gb", t); return float(m.group(1)) if m else np.nan
    if "mb" in t:
        m = re.search(r"(\d{2,4})\s*mb", t); return round(float(m.group(1))/1024, 1) if m else np.nan
    m = re.search(r"(\d{1,3}(?:\.\d+)?)", t)
    if not m: return np.nan
    n = float(m.group(1))
    return round(n/1024,1) if n>64 else n

def parse_storage_gb(s):
    if s is None: return np.nan
    t = str(s).lower()
    # "8/128" → take the max as storage
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    if "tb" in t:
        m = re.search(r"(\d+(?:\.\d+)?)\s*tb", t)
        if m: return float(m.group(1))*1024
    if "gb" in t or "/" in t:
        return max(nums) if nums else np.nan
    if "mb" in t and nums:
        # storage in MB → convert
        return round(max(nums)/1024, 1)
    return max(nums) if nums else np.nan

def parse_camera_mp(s):
    if s is None: return np.nan
    t = str(s).lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*mp", t)
    if m: return float(m.group(1))
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    # choose a plausible MP (5–250)
    for x in nums:
        if 2 <= x <= 250: return x
    return np.nan

def parse_weight_g(s):
    if s is None: return np.nan
    t = str(s).lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*oz", t)
    if m:
        return round(float(m.group(1))*28.3495,1)
    m = re.search(r"(\d+(?:\.\d+)?)\s*g\b", t)
    if m:
        return float(m.group(1))
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    for x in nums:
        if 80 <= x <= 350: return x
    return np.nan

def infer_brand_from_model(model_str):
    if not isinstance(model_str, str): return None
    s = model_str.strip().lower()
    for b in KNOWN_BRANDS:
        if s.startswith(b+" ") or s.startswith(b+"-") or s == b:
            return b.title()
    return None

FEATURE_KEYS = {
    "5G": ["5g"],
    "Wireless charging": ["wireless charging","wireless charge","qi","magsafe"],
    "Water/dust resistant": ["ip69","ip68","ip67","water","dust"],
    "Stereo speakers": ["stereo speakers"],
    "eSIM": ["esim"],
    "Foldable": ["fold","flip"],
    "Stylus support": ["stylus","s-pen","pencil"],
    "Expandable storage": ["microsd","sd card","expandable"],
    "Fast charging": ["fast charge","fast charging","supercharge","warp charge","quick charge"]
}

def load_any_csvs(raw_dir: Path, debug=False):
    rows = []
    report = []
    csv_paths = list(raw_dir.rglob("*.csv"))
    if debug: print(f"🔎 Found {len(csv_paths)} CSV files under {raw_dir}")

    for p in csv_paths:
        df, err = read_csv_smart(p)
        rows_in = len(df)
        mapped = {"brand": None, "model": None, "release": None, "price": None,
                  "display": None, "battery": None, "ram": None, "storage": None,
                  "camera": None, "os": None, "weight": None, "features": None}
        reason = ""

        if df.empty:
            report.append({"file": str(p), "rows_in": rows_in, "rows_out": 0, "mapped": mapped, "reason": f"read_failed_or_empty: {err}"})
            if debug: print(f"  • {p.name}: read failed/empty ({err})")
            continue

        b = col(df, SYN["brand"]);   m = col(df, SYN["model"])
        y = col(df, SYN["release"]); pr = col(df, SYN["price"])
        di = col(df, SYN["display"]); bt = col(df, SYN["battery"])
        ra = col(df, SYN["ram"]);    st = col(df, SYN["storage"])
        ca = col(df, SYN["camera"]); os_ = col(df, SYN["os"])
        we = col(df, SYN["weight"]); fe = col(df, SYN["features"])

        mapped.update({"brand":b,"model":m,"release":y,"price":pr,"display":di,"battery":bt,"ram":ra,"storage":st,"camera":ca,"os":os_,"weight":we,"features":fe})

        tmp = pd.DataFrame()
        tmp["Brand"] = df[b] if b else None
        tmp["Model"] = df[m] if m else None
        tmp["ReleaseYear"] = df[y].apply(parse_year) if y else np.nan
        tmp["PriceUSD"] = pd.to_numeric(df[pr], errors="coerce") if pr else np.nan
        tmp["DisplayInches"] = df[di].apply(parse_inches) if di else np.nan
        tmp["Battery_mAh"] = df[bt].apply(parse_mah) if bt else np.nan
        tmp["RAM_GB"] = df[ra].apply(parse_ram_gb) if ra else np.nan
        tmp["Storage_GB"] = df[st].apply(parse_storage_gb) if st else np.nan
        tmp["MainCameraMP"] = df[ca].apply(parse_camera_mp) if ca else np.nan
        tmp["OS"] = df[os_] if os_ else None
        tmp["Weight_g"] = df[we].apply(parse_weight_g) if we else np.nan

        # If Brand missing but Model present, try to infer brand
        if b is None and m is not None:
            inferred = df[m].astype(str).apply(infer_brand_from_model)
            tmp["Brand"] = tmp["Brand"].where(tmp["Brand"].notna(), inferred)

        # Features
        if fe:
            feats = df[fe].astype(str)
        else:
            text_cols = [c for c in [di, os_, fe] if c]
            feats = df[text_cols].astype(str).agg(" ".join, axis=1) if text_cols else pd.Series([""]*len(df))
        feats_l = feats.str.lower()
        flags = []
        for label, keys in FEATURE_KEYS.items():
            flags.append(np.where(feats_l.str.contains("|".join([re.escape(k) for k in keys])), label, ""))
        tmp["NotableFeatures"] = pd.Series(["; ".join([f for f in row if f]) for row in zip(*flags)])

        tmp["SourceFiles"] = str(p)
        tmp["ID"] = None
        tmp["Slug"] = tmp.apply(lambda r: re.sub(r"[^a-z0-9]+","-", f"{str(r['Brand']).lower()}-{str(r['Model']).lower()}").strip("-"), axis=1)

        # Cleanup
        tmp["Brand"] = tmp["Brand"].astype(str).str.strip()
        tmp["Model"] = tmp["Model"].astype(str).str.strip()
        tmp = tmp[(tmp["Brand"].notna()) & (tmp["Model"].notna()) & (tmp["Brand"]!="None") & (tmp["Model"]!="None")]
        rows_out = len(tmp)

        if debug:
            print(f"  • {p.name}: read={rows_in}, mapped_brand={b}, mapped_model={m}, out_rows={rows_out}")

        report.append({"file": str(p), "rows_in": rows_in, "rows_out": rows_out, "mapped": mapped, "reason": "" if rows_out>0 else "no_brand_or_model_after_mapping"})
        if rows_out > 0:
            rows.append(tmp)

    if not rows:
        return pd.DataFrame(columns=SCHEMA), pd.DataFrame(report)

    out = pd.concat(rows, ignore_index=True)

    # Prefer better-filled rows when de-duplicating (Brand+Model+Year)
    fill_cols = ["PriceUSD","DisplayInches","Battery_mAh","RAM_GB","Storage_GB","MainCameraMP","Weight_g"]
    out["__fill"] = out[fill_cols].notna().sum(axis=1) + out["NotableFeatures"].astype(bool).astype(int)
    out = (out.sort_values(["Brand","Model","ReleaseYear","__fill"], ascending=[True,True,True,False])
              .drop_duplicates(subset=["Brand","Model","ReleaseYear"], keep="first")
              .drop(columns="__fill"))

    return out[SCHEMA], pd.DataFrame(report)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw_dir", required=True)
    ap.add_argument("--out_csv", required=True)
    ap.add_argument("--out_json", required=True)
    ap.add_argument("--min_year", type=int, default=2000)
    ap.add_argument("--max_year", type=int, default=2035)
    ap.add_argument("--limit", type=int, default=0, help="0 = no cap")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--report", default="data/processed/ingest_report.csv")
    args = ap.parse_args()

    raw = Path(args.raw_dir)
    raw.mkdir(parents=True, exist_ok=True)

    df, report = load_any_csvs(raw, debug=args.debug)

    # year window
    df = df[(df["ReleaseYear"].fillna(0) >= args.min_year) & (df["ReleaseYear"].fillna(9999) <= args.max_year)]

    if args.limit and args.limit > 0:
        df = df.head(args.limit)

    Path(args.out_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out_csv, index=False)
    df.to_json(args.out_json, orient="records")

    # write ingest report (flatten mapped dict)
    if not report.empty:
        mapped_df = report.copy()
        mapped_cols = pd.json_normalize(mapped_df["mapped"])
        mapped_df = pd.concat([mapped_df.drop(columns=["mapped"]), mapped_cols], axis=1)
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        mapped_df.to_csv(args.report, index=False)

    print(f"✅ Wrote {len(df)} rows to:\n  - {args.out_csv}\n  - {args.out_json}")
    print(f"🧾 Ingest report: {args.report}")

if __name__ == "__main__":
    main()
