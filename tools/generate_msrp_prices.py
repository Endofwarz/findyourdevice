import pandas as pd
import csv
import time
import re

# This script requires the google-generativeai and python-dotenv packages.
# Please install them using: pip install google-generativeai python-dotenv
import google.generativeai as genai

import os
from dotenv import load_dotenv

# IMPORTANT: Configure your Gemini API key in the backend/.env file.
# You can get a key from https://aistudio.google.com/app/apikey
load_dotenv(dotenv_path="backend/.env")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def list_models():
    """Lists available Gemini models."""
    if not GEMINI_API_KEY or GEMINI_API_KEY == "YOUR_GEMINI_API_KEY":
        print("Error: Gemini API key not configured.")
        return False
    genai.configure(api_key=GEMINI_API_KEY)
    print("Available models:")
    models_found = False
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(m.name)
            models_found = True
    if not models_found:
        print("No models found that support generateContent.")
    return models_found

def get_msrp_from_gemini(brand, phone_model, gemini_model_name):
    """
    Gets the MSRP for a phone from Gemini.
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == "YOUR_GEMINI_API_KEY":
        print("Error: Gemini API key not configured.")
        return None

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(gemini_model_name)

    prompt = f"What is the Manufacturer's Suggested Retail Price (MSRP) of the {brand} {phone_model} in EUR? Please provide only the price as a number (e.g., 799.99)."
    try:
        response = model.generate_content(prompt)
        price_str = response.text.strip()
        # Use regex to find the first number in the string, which might have commas or dots
        match = re.search(r'(\d[\d,.]*)', price_str)
        if match:
            price = float(match.group(1).replace(",", ""))
            return price
    except Exception as e:
        print(f"Error getting price for {brand} {phone_model}: {e}")
    return None

import sys
sys.path.append('.')

from backend.gsma_scraper import _search_phone_url
from tools.gsmarena_scraper import get_price_from_gsmarena

def generate_msrp_prices():
    """
    Generates a CSV file with MSRP prices for phones from 2023 onwards.
    """
    # Load the phones dataset
    try:
        df = pd.read_csv("data/processed/phones_clean.csv")
    except FileNotFoundError:
        print("Error: data/processed/phones_clean.csv not found.")
        return

    # Filter for phones from 2023 onwards
    df_2023_onwards = df[df["ReleaseYear"] >= 2023].copy()

    # Prepare data for the new CSV
    msrp_data = []

    for index, row in df_2023_onwards.iterrows():
        brand = row["Brand"]
        model = row["Model"]
        slug = row["Slug"]
        
        # Find the phone page URL
        url = _search_phone_url(brand, model)

        if not url:
            print(f"Could not find URL for {brand} {model}")
            continue

        # The price is on a separate tab, so we need to modify the URL
        price_url = url.replace(".php", "-price.php")

        print(f"Getting price for {brand} {model} from {price_url}...")
        price = get_price_from_gsmarena(price_url)
        if price:
            msrp_data.append([slug, price])
            print(f"  -> Price: {price} EUR")
        else:
            print("  -> Price not found.")
        # Add a delay to avoid getting blocked
        time.sleep(1)

    # Write to CSV
    with open("data/processed/msrp_prices.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["slug", "PriceEUR"])
        writer.writerows(msrp_data)

    print("\nSuccessfully generated data/processed/msrp_prices.csv")

if __name__ == "__main__":
    generate_msrp_prices()
