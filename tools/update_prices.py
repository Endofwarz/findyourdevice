import os
import pandas as pd
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from backend.llm import chat_complete # Assuming backend.llm is accessible
from backend.config import EUR_PER_USD # Assuming EUR_PER_USD is accessible

# --- Configuration ---
PHONES_CSV_PATH = Path("data/processed/phones_clean.csv") # Or phones_gsma.csv
PRICES_CSV_PATH = Path("data/processed/prices.csv")
LLM_MODEL_PRICE_UPDATE = "llama-3.1-70b-versatile" # Use the more powerful model for offline updates
PRICE_CACHE_TTL_HOURS = 24

# Ensure output directory exists
PRICES_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

def load_prices_cache() -> pd.DataFrame:
    if PRICES_CSV_PATH.exists():
        df = pd.read_csv(PRICES_CSV_PATH)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
    return pd.DataFrame(columns=["slug", "price", "currency", "timestamp"])

def save_prices_cache(df: pd.DataFrame):
    df.to_csv(PRICES_CSV_PATH, index=False)

def update_prices_script():
    print(f"Starting price update script at {datetime.now()}")

    # Load existing phones
    if not PHONES_CSV_PATH.exists():
        print(f"Error: Phones CSV not found at {PHONES_CSV_PATH}")
        return

    phones_df = pd.read_csv(PHONES_CSV_PATH)
    prices_cache_df = load_prices_cache()

    updated_prices = []
    for index, row in phones_df.iterrows():
        brand = row["Brand"]
        model = row["Model"]
        slug = row["Slug"]

        # Check if price is in cache and not expired
        cached_price = prices_cache_df[prices_cache_df["slug"] == slug]
        if not cached_price.empty:
            last_updated = cached_price["timestamp"].iloc[0]
            if datetime.now() - last_updated < timedelta(hours=PRICE_CACHE_TTL_HOURS):
                updated_prices.append(cached_price.iloc[0].to_dict())
                print(f"  - {brand} {model}: Price found in cache.")
                continue

        print(f"  - {brand} {model}: Fetching price via LLM...")
        price, _ = fetch_price_via_llm_for_update(brand, model) # Use a dedicated function for this script
        if price:
            updated_prices.append({
                "slug": slug,
                "price": price,
                "currency": "EUR",
                "timestamp": datetime.now()
            })
            print(f"    -> Fetched: {price} EUR")
        else:
            print(f"    -> Failed to fetch price for {brand} {model}")
            # If LLM fails, try to use existing price from cache if available, even if expired
            if not cached_price.empty:
                updated_prices.append(cached_price.iloc[0].to_dict())


    new_prices_df = pd.DataFrame(updated_prices)
    save_prices_cache(new_prices_df)
    print(f"Finished price update script. {len(new_prices_df)} prices updated/cached.")

def fetch_price_via_llm_for_update(brand: str, model: str) -> tuple[float | None, str | None]:
    """
    Uses LLM to find the current price of a phone for the update script.
    Returns (price_eur, currency) or (None, None) if not available.
    """
    # Ensure USE_LLM is enabled for this script's context
    if os.getenv("USE_LLM", "0") != "1":
        print("[LLM price update] USE_LLM is not enabled in environment.")
        return None, None

    try:
        prompt = (
            f"What is the current approximate retail price of the {brand} {model} phone in EUR? "
            "Provide only the price as a number (e.g., 799.99). "
            "If you cannot find a price, respond with 'None'."
        )
        # Use the more powerful model for this background task
        response_text = chat_complete([{"role": "user", "content": prompt}], model=LLM_MODEL_PRICE_UPDATE, max_tokens=20, temperature=0.1)

        if response_text and response_text.strip().lower() != "none":
            match = re.search(r"(\d[\d\.,]*)", response_text)
            if match:
                price_str = match.group(1).replace(",", ".")
                price = float(price_str)
                return price, "EUR" # Assume EUR as requested
    except Exception as e:
        print(f"[LLM price update] failed for {brand} {model}: {e}")
    return None, None

if __name__ == "__main__":
    # This script needs USE_LLM=1 and GROQ_API_KEY set in its environment
    # when run manually or via a cron job.
    update_prices_script()