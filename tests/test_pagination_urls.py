"""Fast pagination chooser tests: no Chromium or network needed."""
import pytest

from scraper.pagination import _absolute_catalog_url, next_catalog_url

BASE = "https://sklepsoltech.pl/pl/c/Panele-fotowoltaiczne/13"


class Link:
    def __init__(self, href):
        self.href = href

    def get_attribute(self, name):
        assert name == "href"
        return self.href


class Locator:
    def __init__(self, hrefs):
        self.hrefs = hrefs

    def count(self):
        return len(self.hrefs)

    def nth(self, i):
        return Link(self.hrefs[i])


class Page:
    url = BASE

    def __init__(self, hrefs, broken_text=False):
        self.hrefs = hrefs
        self.broken_text = broken_text

    def get_by_role(self, role, name, exact):
        assert (role, name, exact) == ("link", "Następne produkty", True)
        return Locator(self.hrefs)

    def get_by_text(self, text, exact):
        assert text == "Następne produkty" and exact
        return Locator(["x"] if self.broken_text else [])


def test_two_controls_same_destination_are_valid():
    assert next_catalog_url(Page(["/pl/c/Panele-fotowoltaiczne/13/2", BASE + "/2"]), 1) == BASE + "/2"


def test_two_different_pages_are_rejected():
    with pytest.raises(RuntimeError, match="2 roznych adresow"):
        next_catalog_url(Page(["/pl/c/Panele-fotowoltaiczne/13/2", "/pl/c/Panele-fotowoltaiczne/13/3"]), 1)


def test_empty_link_is_rejected():
    with pytest.raises(RuntimeError, match="nie ma href"):
        next_catalog_url(Page([" "]), 1)


def test_javascript_and_external_redirects_rejected():
    for href in ["javascript:alert(1)", "https://evil.example/next", "//evil.example/next"]:
        with pytest.raises(RuntimeError, match="poza aktualny sklep|niedozwolonego URL"):
            _absolute_catalog_url(BASE, href)


def test_fragment_is_not_part_of_page_identity():
    assert next_catalog_url(Page([BASE + "/2#top", BASE + "/2#bottom"]), 1) == BASE + "/2"


def test_true_last_page_returns_none():
    assert next_catalog_url(Page([]), 3) is None


def test_broken_control_without_href_rejected():
    with pytest.raises(RuntimeError, match="brak prawidlowego linku"):
        next_catalog_url(Page([], broken_text=True), 1)
