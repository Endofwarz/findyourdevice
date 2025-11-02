import pandas as pd
import csv
import time
import re

# This script requires the google-generativeai package.
# Please install it using: pip install google-generativeai
import google.generativeai as genai

# IMPORTANT: Configure your Gemini API key here.
# You can get a key from https://aistudio.google.com/app/apikey
GEMINI_API_KEY = "AIzaSyAEL1gcVE0TDO2D3JG7nQXXRQxUOW1jlSU"

def get_msrp_from_gemini(brand, model):
    """
    Gets the MSRP for a phone from Gemini.
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == "YOUR_GEMINI_API_KEY":
        print("Error: Gemini API key not configured.")
        return None

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.0-pro')

    prompt = f"What is the Manufacturer's Suggested Retail Price (MSRP) of the {brand} {model} in EUR? Please provide only the price as a number (e.g., 799.99)."
    try:
        response = model.generate_content(prompt)
        price_str = response.text.strip()
        # Use regex to find the first number in the string, which might have commas or dots
        match = re.search(r'(\d[\d,.]*)', price_str)
        if match:
            price = float(match.group(1).replace(",", ""))
            return price
    except Exception as e:
        print(f"Error getting price for {brand} {model}: {e}")
    return None

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
        print(f"Getting price for {brand} {model}...")
        price = get_msrp_from_gemini(brand, model)
        if price:
            msrp_data.append([slug, price])
            print(f"  -> Price: {price} EUR")
        else:
            print("  -> Price not found.")
        # Add a delay to avoid hitting API rate limits
        time.sleep(1)

    # Write to CSV
    with open("data/processed/msrp_prices.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["slug", "PriceEUR"])
        writer.writerows(msrp_data)

    print("\nSuccessfully generated data/processed/msrp_prices.csv")

if __name__ == "__main__":
    generate_msrp_prices()