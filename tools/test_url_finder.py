import sys
sys.path.append('.')

from backend.gsma_scraper import _find_phone_page

if __name__ == '__main__':
    brand = "Samsung"
    model = "Galaxy S24"
    
    print(f"Finding URL for {brand} {model}...")
    url = _find_phone_page(brand, model)
    
    if url:
        print(f"Found URL: {url}")
    else:
        print("Could not find URL.")
