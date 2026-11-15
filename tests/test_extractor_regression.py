"""Offline, real-Chromium regression tests for Soltech HTML contracts.

No retailer requests or PostgreSQL connections are performed. All page.goto
calls are intercepted and fulfilled from tests/fixtures/*.html.

The sample files are deliberately small, synthetic DOM contracts, not copies
of the retailer's current site. A layout migration requires fixture review.
"""

import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from playwright.sync_api import sync_playwright

import scraper.extractor as extractor
from scraper.parser import parse_product_tile


FIXTURES = Path(__file__).parent / "fixtures"
CATALOG = "/pl/c/Panele-fotowoltaiczne/13"
OFFLINE_ORIGIN = "http://127.0.0.1:8765"


def html(filename: str) -> str:
    return (FIXTURES / filename).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def use_offline_origin(monkeypatch):
    # Even page.goto uses a loopback hostname, never the retailer.
    monkeypatch.setattr(extractor, "BASE_URL", OFFLINE_ORIGIN + CATALOG)


@pytest.fixture(scope="module")
def browser():
    """Use Playwright's Chromium, optionally an explicitly configured binary."""
    with sync_playwright() as playwright:
        launch_args = {"headless": True}
        local_binary = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        if local_binary:
            launch_args["executable_path"] = local_binary
            launch_args["args"] = ["--no-sandbox"]
        browser_instance = playwright.chromium.launch(**launch_args)
        try:
            yield browser_instance
        finally:
            browser_instance.close()


class OfflinePage:
    """Real Playwright DOM selectors + fixture-backed, network-free navigation.

    Page.goto is the only simulated part. Chromium parses the HTML and all
    locators, attributes, roles and XPath run on the real browser DOM.
    """

    def __init__(self, real_page):
        self._page = real_page
        self.url = "about:blank"
        self.pages = {}
        self.statuses = {}
        self.requested = []

    def configure(self, pages, statuses=None):
        self.pages = pages
        self.statuses = statuses or {}
        self.requested.clear()
        return self.requested

    def goto(self, url, *, wait_until, timeout):
        if not url.startswith(OFFLINE_ORIGIN + "/"):
            raise AssertionError(f"Unexpected non-offline navigation: {url}")
        path = urlsplit(url).path
        self.requested.append(path)
        self.url = url
        # Mimic HTTP response and update the real browser's DOM with local HTML.
        if path not in self.pages:
            return SimpleNamespace(status=404)
        self._page.set_content(self.pages[path], wait_until="domcontentloaded")
        return SimpleNamespace(status=self.statuses.get(path, 200))

    def __getattr__(self, name):
        return getattr(self._page, name)


@pytest.fixture
def page(browser):
    real_page = browser.new_page()
    try:
        yield OfflinePage(real_page)
    finally:
        real_page.close()


def serve_offline(page, pages: dict[str, str], *, statuses: dict[str, int] | None = None):
    """Configure fake navigation; zero network calls are made in all tests."""
    return page.configure(pages, statuses)


def test_end_to_end_pagination_dedup_and_filtering(page, capsys):
    requested = serve_offline(page, {
        CATALOG: html("catalog_page_1.html"),
        f"{CATALOG}/2": html("catalog_page_2.html"),
    })
    run_id = uuid4()
    panels = extractor._scrape_catalog(page, run_id)

    assert requested == [CATALOG, f"{CATALOG}/2"]
    assert len(panels) == 4
    assert all(panel.scrape_run_id == run_id for panel in panels)
    assert len({panel.source_url for panel in panels}) == 4
    assert sorted(panel.power_text for panel in panels) == ["575 W", "615 W", "620 W", "640 W"]
    assert sum(panel.is_available for panel in panels) == 3
    assert panels[0].source_url == "https://sklepsoltech.pl/pl/p/tw-solar-575/1001"
    assert "Pominietych duplikatow: 1" in capsys.readouterr().out


def test_repeated_page_from_broken_pagination_fails(page):
    serve_offline(page, {
        CATALOG: html("catalog_page_1.html"),
        f"{CATALOG}/2": html("catalog_repeated.html"),
    })
    with pytest.raises(RuntimeError, match="nie zawiera nowych produktow"):
        extractor._scrape_catalog(page, uuid4())


def test_missing_catalog_section_fails(page):
    serve_offline(page, {CATALOG: html("catalog_missing_section.html")})
    with pytest.raises(RuntimeError, match="Lista produktów"):
        extractor._scrape_catalog(page, uuid4())


def test_missing_product_href_is_not_silently_saved(page):
    serve_offline(page, {CATALOG: html("catalog_missing_url.html")})
    with pytest.raises(RuntimeError, match="Produkt bez source_url"):
        extractor._scrape_catalog(page, uuid4())


def test_visible_broken_next_link_is_not_treated_as_end_of_catalog(page):
    serve_offline(page, {CATALOG: html("catalog_missing_next_href.html")})
    with pytest.raises(RuntimeError, match="brak prawidlowego linku"):
        extractor._scrape_catalog(page, uuid4())


def test_http_error_fails_before_parser(page):
    serve_offline(page, {CATALOG: html("catalog_page_1.html")}, statuses={CATALOG: 503})
    with pytest.raises(RuntimeError, match="Blad HTTP na stronie 1"):
        extractor._scrape_catalog(page, uuid4())


def test_looping_pagination_fails(page):
    first_page = html("catalog_page_1.html").replace(
        f'href="{CATALOG}/2"', f'href="{CATALOG}"'
    )
    serve_offline(page, {CATALOG: first_page})
    with pytest.raises(RuntimeError, match="petle paginacji"):
        extractor._scrape_catalog(page, uuid4())


def test_max_page_safety_limit(page, monkeypatch):
    serve_offline(page, {CATALOG: html("catalog_page_1.html")})
    monkeypatch.setattr(extractor, "MAX_PAGES", 1)
    with pytest.raises(RuntimeError, match="Osiagnieto limit 1 stron"):
        extractor._scrape_catalog(page, uuid4())


def test_missing_price_is_skipped_but_other_product_kept(page):
    content = html("catalog_repeated.html").replace(
        'name="Panel fotowoltaiczny JA Solar 640W" price="459.90"',
        'name="Panel fotowoltaiczny JA Solar 640W"'
    )
    serve_offline(page, {CATALOG: content})
    panels = extractor._scrape_catalog(page, uuid4())
    assert len(panels) == 1
    assert panels[0].power_text == "575 W"


def test_ambiguous_catalog_heading_fails(page):
    content = html("catalog_repeated.html").replace(
        "<h2>Lista produktów</h2>",
        "<h2>Lista produktów</h2><h3>Lista produktów</h3>",
    )
    serve_offline(page, {CATALOG: content})
    with pytest.raises(RuntimeError, match="Znaleziono: 2"):
        extractor._scrape_catalog(page, uuid4())


def test_parser_uses_real_dom_for_relative_url_and_unavailable(page):
    page.set_content(html("catalog_page_1.html"))
    tiles = page.locator("#product-catalog product-tile")
    run_id = uuid4()
    available = parse_product_tile(tiles.nth(0), run_id)
    unavailable = parse_product_tile(tiles.nth(1), run_id)
    inverter = parse_product_tile(tiles.nth(2), run_id)
    without_power = parse_product_tile(tiles.nth(3), run_id)

    assert available is not None and available.is_available is True
    assert available.price_text == "364.07"
    assert unavailable is not None and unavailable.is_available is False
    assert unavailable.source_url == "https://sklepsoltech.pl/pl/p/ja-solar-640/1002"
    assert inverter is None
    assert without_power is None


def test_parser_returns_none_for_missing_href_without_network(page):
    page.set_content(html("catalog_missing_url.html"))
    panel = parse_product_tile(page.locator("product-tile"), uuid4())
    assert panel is not None
    assert panel.source_url is None


def test_duplicate_next_links_to_same_destination_are_accepted(page):
    one = html("catalog_page_1.html")
    one = one.replace(
        '<nav><a href="/pl/c/Panele-fotowoltaiczne/13/2">Następne produkty</a></nav>',
        '<nav><a href="/pl/c/Panele-fotowoltaiczne/13/2">Następne produkty</a>'
        '<a href="http://127.0.0.1:8765/pl/c/Panele-fotowoltaiczne/13/2">Następne produkty</a></nav>',
    )
    requested = serve_offline(page, {
        CATALOG: one,
        f"{CATALOG}/2": html("catalog_page_2.html"),
    })
    panels = extractor._scrape_catalog(page, uuid4())
    assert requested == [CATALOG, f"{CATALOG}/2"]
    assert len(panels) == 4


def test_duplicate_next_links_to_different_destinations_fail(page):
    one = html("catalog_page_1.html")
    one = one.replace(
        '<nav><a href="/pl/c/Panele-fotowoltaiczne/13/2">Następne produkty</a></nav>',
        '<nav><a href="/pl/c/Panele-fotowoltaiczne/13/2">Następne produkty</a>'
        '<a href="/pl/c/Panele-fotowoltaiczne/13/3">Następne produkty</a></nav>',
    )
    serve_offline(page, {CATALOG: one})
    with pytest.raises(RuntimeError, match="2 roznych adresow"):
        extractor._scrape_catalog(page, uuid4())


def test_duplicate_next_link_with_no_href_does_not_hide_valid_link(page):
    one = html("catalog_page_1.html").replace(
        '<nav><a href="/pl/c/Panele-fotowoltaiczne/13/2">Następne produkty</a></nav>',
        '<nav><a href="/pl/c/Panele-fotowoltaiczne/13/2">Następne produkty</a>'
        '<a>Następne produkty</a></nav>',
    )
    # Missing href does not enter ARIA link matches: assert the parser does not
    # silently suppress the valid link; an explicit stricter check can follow
    # if live markup proves this situation is common.
    serve_offline(page, {CATALOG: one, f"{CATALOG}/2": html("catalog_page_2.html")})
    result = extractor._scrape_catalog(page, uuid4())
    assert len(result) == 4
