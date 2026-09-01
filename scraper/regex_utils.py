import re


POWER_PATTERN = re.compile(
    r"(?<!\d)([3-8]\d{2})(?:W|Wp|M)?(?!\d)",
    re.IGNORECASE,
)

PERCENT_PATTERN = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*%",
    re.IGNORECASE,
)


def extract_power(text: str) -> int | None:
    matches = POWER_PATTERN.findall(text)

    if not matches:
        return None

    powers = [int(match) for match in matches]

    return max(powers)


def extract_percent(text: str) -> float | None:
    match = PERCENT_PATTERN.search(text)

    if not match:
        return None

    return float(match.group(1).replace(",", "."))