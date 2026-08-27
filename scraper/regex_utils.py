import re

POWER_PATTERN = re.compile(r"(\d+)\s*W")
PERCENT_PATTERN = re.compile(r"(\d+[.,]?\d*)\s*%")
PRICE_PATTERN = re.compile(r"(\d+[.,]\d+)")