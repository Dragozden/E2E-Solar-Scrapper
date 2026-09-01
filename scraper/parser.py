from playwright.sync_api import Locator

from scraper.models import RawPanel
from scraper.regex_utils import extract_power


PANEL_PREFIX = "panel fotowoltaiczny"


def is_panel(name: str) -> bool:
    return name.strip().lower().startswith(PANEL_PREFIX)


def parse_product_tile(tile: Locator) -> RawPanel | None:
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

    return RawPanel(
        title=name,
        price_text=price,
        power_text=f"{power} W",
        efficiency_text="",
        bifaciality_text="",
        source_url="",
        is_available=not is_unavailable,
    )