import requests
from bs4 import BeautifulSoup
import re

def scrape_price_from_idealo(brand: str, model: str) -> float | None:
    """
    Scrapes the price of a phone from idealo.de.
    """
    search_term = f"{brand} {model}"
    url = f"https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q={search_term}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, "html.parser")

        # Find the price element
        price_element = soup.find("div", class_="offer-price")
        if price_element:
            price_text = price_element.text.strip()
            # The price is in the format "ab 1.234,56 €"
            # We need to extract the number and convert it to a float
            price_match = re.search(r"(\d[\d\.,]*)", price_text)
            if price_match:
                price_str = price_match.group(1).replace(".", "").replace(",", ".")
                return float(price_str)

    except requests.exceptions.RequestException as e:
        print(f"[idealo] API request failed for '{search_term}': {e}")
    except Exception as e:
        print(f"[idealo] Error processing response for '{search_term}': {e}")

    return None

if __name__ == "__main__":
    brand = "Samsung"
    model = "Galaxy S24"
    price = scrape_price_from_idealo(brand, model)
    if price:
        print(f"The price for {brand} {model} is {price} EUR")
    else:
        print(f"Could not find the price for {brand} {model}")
