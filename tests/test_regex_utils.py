from scraper.regex_utils import POWER_PATTERN

def test_power_regex():
    match = POWER_PATTERN.search("505 W")

    assert match.group(1) == "505"