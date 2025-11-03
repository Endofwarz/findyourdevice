import os
import re
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables from backend/.env
load_dotenv(dotenv_path="backend/.env")

# Get the API key from the environment
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def get_msrp_from_gemini_debug(brand, phone_model, gemini_model_name):
    """
    Gets the MSRP for a phone from Gemini with detailed error logging.
    """
    if not GEMINI_API_KEY:
        print("Error: Gemini API key not configured.")
        return None

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(gemini_model_name)

        prompt = f"What is the Manufacturer's Suggested Retail Price (MSRP) of the {brand} {phone_model} in EUR? Please provide only the price as a number (e.g., 799.99)."
        
        print(f"Using model: {gemini_model_name}")
        response = model.generate_content(prompt)
        
        price_str = response.text.strip()
        match = re.search(r'(\d[\d,.]*)', price_str)
        if match:
            price = float(match.group(1).replace(",", ""))
            return price
        else:
            print(f"Could not parse price from response: {price_str}")
            return None

    except Exception as e:
        print(f"An error occurred: {e}")
        return None

if __name__ == "__main__":
    # Test with a specific phone and model
    test_brand = "Google"
    test_phone_model = "Pixel 8 Pro"
    # Let's use a model that we know is available
    gemini_model_to_test = "gemini-pro-latest"
    
    print(f"--- Testing with model: {gemini_model_to_test} ---")
    price = get_msrp_from_gemini_debug(test_brand, test_phone_model, gemini_model_to_test)

    if price is not None:
        print(f"Successfully retrieved price: {price} EUR")
    else:
        print("Failed to retrieve price.")
