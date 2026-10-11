from unittest.mock import Mock
from uuid import uuid4

from scraper.parser import parse_product_tile
from scraper.parser import extract_source_url

def test_parser_handles_missing_source_url():
    tile = Mock()

    tile.get_attribute.side_effect = lambda attribute: {
        "name": "Panel fotowoltaiczny Test 500W",
        "price": "400.00",
    }.get(attribute)

    tile.locator.return_value.first.get_attribute.return_value = None
    tile.locator.return_value.count.return_value = 0

    result = parse_product_tile(
        tile,
        uuid4(),
    )

    assert result is not None
    assert result.source_url is None

def test_source_url_when_link_does_not_exist():
    tile = Mock()

    tile.locator.return_value.count.return_value = 0

    result = extract_source_url(tile)

    assert result is None


def test_source_url_when_href_is_missing():
    tile = Mock()

    tile.locator.return_value.count.return_value = 1
    tile.locator.return_value.first.get_attribute.return_value = None

    result = extract_source_url(tile)

    assert result is None


def test_source_url_when_href_is_relative():
    tile = Mock()

    tile.locator.return_value.count.return_value = 1
    tile.locator.return_value.first.get_attribute.return_value = (
        "/pl/p/Panel-testowy/123"
    )

    result = extract_source_url(tile)

    assert result == (
        "https://sklepsoltech.pl/pl/p/Panel-testowy/123"
    )