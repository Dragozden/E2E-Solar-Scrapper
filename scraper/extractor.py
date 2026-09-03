from playwright.sync_api import sync_playwright

from scraper.parser import parse_product_tile
from uuid import uuid4


BASE_URL = "https://sklepsoltech.pl/pl/c/Panele-fotowoltaiczne/13"
TOTAL_PAGES = 12


def scrape_panels(scrape_run_id: UUID) -> list[RawPanel]:
    panels = []
    scrape_run_id = uuid4()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for current_page in range(1, TOTAL_PAGES + 1):

            url = (
                BASE_URL
                if current_page == 1
                else f"{BASE_URL}/{current_page}"
            )

            print(
                f"Scrapowanie strony "
                f"{current_page}/{TOTAL_PAGES}"
            )

            page.goto(
                url,
                wait_until="domcontentloaded"
            )

            product_list = page.get_by_text(
                "Lista produktów",
                exact=True,
            )

            if product_list.count() != 1:
                raise RuntimeError(
                    f"Nie znaleziono jednoznacznej sekcji "
                    f"'Lista produktów' na stronie "
                    f"{current_page}. "
                    f"Znaleziono: {product_list.count()}"
                )

            product_container = product_list.locator(
                "xpath=ancestor::*[.//product-tile][1]"
            )

            tiles = product_container.locator(
                "product-tile"
            ).all()

            print(
                f"Strona {current_page}: "
                f"{len(tiles)} produktów"
            )

            for tile in tiles:
                panel = parse_product_tile(tile, scrape_run_id,)

                if panel is not None:
                    panels.append(panel)

        browser.close()

    print(f"\nŁącznie produktów: {len(panels)}")

    return panels