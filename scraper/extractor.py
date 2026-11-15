from uuid import UUID
from urllib.parse import urljoin

from playwright.sync_api import Page, sync_playwright

from scraper.models import RawPanel
from scraper.parser import parse_product_tile


BASE_URL = "https://sklepsoltech.pl/pl/c/Panele-fotowoltaiczne/13"
MAX_PAGES = 50  # Safety ceiling, not an assumed catalog length.


def _scrape_catalog(page: Page, scrape_run_id: UUID) -> list[RawPanel]:
    """Parse a paginated catalog using the supplied browser page.

    Keeping navigation independent of browser startup makes offline regression
    tests possible without contacting the retailer or PostgreSQL.
    """
    panels: list[RawPanel] = []
    seen_products: set[str] = set()
    visited_pages: set[str] = set()

    current_url = BASE_URL
    current_page = 1
    duplicates_count = 0

    while current_page <= MAX_PAGES:
        if current_url in visited_pages:
            raise RuntimeError(f"Wykryto petle paginacji: {current_url}")

        visited_pages.add(current_url)
        print(f"\nScrapowanie strony {current_page}: {current_url}")

        response = page.goto(
            current_url,
            wait_until="domcontentloaded",
            timeout=30000,
        )
        if response is None or response.status >= 400:
            raise RuntimeError(f"Blad HTTP na stronie {current_page}")

        product_list = page.get_by_text("Lista produktów", exact=True)
        heading_count = product_list.count()
        if heading_count != 1:
            raise RuntimeError(
                "Nie znaleziono jednoznacznej sekcji 'Lista produktów' "
                f"na stronie {current_page}. Znaleziono: {heading_count}"
            )

        product_container = product_list.locator(
            "xpath=ancestor::*[.//product-tile][1]"
        )
        tile_locator = product_container.locator("product-tile")
        tile_locator.first.wait_for(state="attached", timeout=15000)
        tiles = tile_locator.all()

        new_count = 0
        page_duplicates = 0
        for tile in tiles:
            panel = parse_product_tile(tile, scrape_run_id)
            if panel is None:
                continue

            source_url = str(panel.source_url or "").strip()
            if not source_url:
                raise RuntimeError(
                    f"Produkt bez source_url na stronie {current_page}"
                )

            product_key = urljoin(page.url, source_url)
            if product_key in seen_products:
                page_duplicates += 1
                duplicates_count += 1
                print(f"[DUPLIKAT] {product_key}")
                continue

            seen_products.add(product_key)
            panels.append(panel)
            new_count += 1

        print(
            f"Strona {current_page}: {len(tiles)} kafelkow, "
            f"{new_count} nowych produktow, "
            f"{page_duplicates} duplikatow"
        )
        if new_count == 0:
            raise RuntimeError(
                f"Strona {current_page} nie zawiera nowych produktow. "
                "Sprawdz paginacje lub parser."
            )

        next_page = page.get_by_role(
            "link", name="Następne produkty", exact=True
        )
        if next_page.count() == 0:
            # An <a> without href stops being a 'link' in the accessibility
            # tree. Detect the visible control instead of silently treating
            # it as the last page.
            if page.get_by_text("Następne produkty", exact=True).count() > 0:
                raise RuntimeError(
                    "Wykryto 'Następne produkty', ale brak prawidlowego linku"
                )
            print("\nOsiagnieto koniec katalogu.")
            break

        if next_page.count() != 1:
            raise RuntimeError(
                f"Niejednoznaczna paginacja na stronie {current_page}"
            )

        next_href = next_page.first.get_attribute("href")
        if not next_href or not next_href.strip():
            raise RuntimeError("Link do kolejnej strony nie ma href")

        current_url = urljoin(page.url, next_href)
        current_page += 1
    else:
        raise RuntimeError(
            f"Osiagnieto limit {MAX_PAGES} stron. Sprawdz paginacje."
        )

    print("\n=== PODSUMOWANIE SCRAPINGU ===")
    print(f"Przetworzonych stron: {current_page}")
    print(f"Unikalnych produktow: {len(panels)}")
    print(f"Pominietych duplikatow: {duplicates_count}")
    print(f"Scrape Run ID: {scrape_run_id}")
    return panels


def scrape_panels(scrape_run_id: UUID) -> list[RawPanel]:
    """Production entrypoint (unchanged API): launch Chromium and scrape."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            return _scrape_catalog(browser.new_page(), scrape_run_id)
        finally:
            browser.close()
