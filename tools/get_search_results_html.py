from playwright.sync_api import sync_playwright

def get_search_results_html(query):
    """
    Gets the HTML of the GSMArena search results page.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            url = f"https://www.gsmarena.com/res.php3?sSearch={query}"
            page.goto(url, wait_until='networkidle')
            content = page.content()
            with open('search_results.html', 'w', encoding='utf-8') as f:
                f.write(content)
            print("Successfully saved search results to search_results.html")
        except Exception as e:
            print(f"An error occurred: {e}")
        finally:
            browser.close()

if __name__ == '__main__':
    get_search_results_html("Samsung Galaxy S24")
