from playwright.sync_api import Locator

from scraper.models import RawPanel
from scraper.regex_utils import extract_power
from uuid import UUID
from urllib.parse import urljoin

PANEL_PREFIX = "panel fotowoltaiczny"
BASE_URL = "https://sklepsoltech.pl"

def is_panel(name: str) -> bool:
    return name.strip().lower().startswith(PANEL_PREFIX)


def parse_product_tile(tile: Locator, scrape_run_id: UUID) -> RawPanel | None:
    name = tile.get_attribute("name")
    price = tile.get_attribute("price")

    if not name or not price:
        return None

    name = name.strip()

    # Najważniejszy filtr.
    # Odrzucamy usługi, falowniki, konstrukcje itd.
    if not is_panel(name):
        return None

    power = extract_power(name)

    if power is None:
        return None

    is_unavailable = (
        tile.locator("availability-notifier-btn").count() > 0
    )

    def extract_source_url(tile) -> str:
        href = tile.locator("a").first.get_attribute("href")

        if not href:
            return ""

        return urljoin(BASE_URL, href)
    
    source_url = extract_source_url(tile)

    return RawPanel(
        title=name,
        price_text=price,
        power_text=f"{power} W",
        efficiency_text="",
        bifaciality_text="",
        source_url=source_url,
        is_available=not is_unavailable,
        scrape_run_id=scrape_run_id,
    )