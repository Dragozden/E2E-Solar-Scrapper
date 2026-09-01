from playwright.sync_api import sync_playwright

from scraper.parser import parse_product_tile


BASE_URL = "https://sklepsoltech.pl/pl/c/Panele-fotowoltaiczne/13"
TOTAL_PAGES = 12


def scrape_panels() -> list:
    panels = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for current_page in range(1, TOTAL_PAGES + 1):

            url = (
                BASE_URL
                if current_page == 1
                else f"{BASE_URL}/{current_page}"
            )

            print(f"Scrapowanie strony {current_page}/{TOTAL_PAGES}")

            page.goto(url, wait_until="domcontentloaded")

            page.wait_for_selector(
                "product-tile",
                state="attached",
                timeout=10_000,
            )

            tiles = page.locator("product-tile").all()

            for tile in tiles:
                panel = parse_product_tile(tile)

                if panel is not None:
                    panels.append(panel)

        browser.close()

    return panels