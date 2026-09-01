from scraper.regex_utils import POWER_PATTERN
from scraper.parser import is_panel

def test_power_regex():
    match = POWER_PATTERN.search("505 W")

    assert match.group(1) == "505"

def test_panel_is_detected():
    assert is_panel(
        "Panel fotowoltaiczny DMEGC 515W DM515G12RT"
    )


def test_non_panel_is_rejected():
    assert not is_panel(
        "Uzgodnienie PPOŻ Instalacji Fotowoltaicznej"
    )


def test_inverter_is_rejected():
    assert not is_panel(
        "Inwerter Solplanet 10 kW"
    )