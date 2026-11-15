"""Conservative PV specification extraction from a retailer product detail page.

Retain original label/value pairs for auditability. Numeric values are optional:
unknown units or ambiguous labels must not be silently guessed. No I/O here.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

PARSER_VERSION = "panel-details-v1.1"
SITE = "sklepsoltech.pl"
DETAIL_PATH = re.compile(r"^/pl/p/[^?#]+/\d+/?$")
_NUMBER = re.compile(r"[+-]?\d+(?:[.,]\d+)?")
_DIMENSIONS = re.compile(r"(\d{3,4})\s*[x×X]\s*(\d{3,4})\s*[x×X]\s*(\d{1,3})\s*mm\b", re.I)


def is_allowed_detail_url(url: str) -> bool:
    parts = urlsplit(url)
    return (parts.scheme == "https" and (parts.hostname or "").lower() == SITE
            and not parts.username and not parts.password and parts.port in (None, 443)
            and bool(DETAIL_PATH.fullmatch(parts.path)) and not parts.query and not parts.fragment)


def _key(label: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", label.casefold())
    ascii_text = "".join(c for c in ascii_text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()


def _one_number(value: str, *, unit: str | None = None) -> float | None:
    if unit is not None and not re.search(unit, value, re.I):
        return None
    match = _NUMBER.search(value.replace("\u00a0", " "))
    if not match:
        return None
    try:
        return float(Decimal(match.group(0).replace(",", ".")))
    except InvalidOperation:
        return None


def _section(soup: BeautifulSoup) -> BeautifulSoup | Tag:
    """Prefer an actual description block, never parse recommendations/navigation."""
    for selector in ("#projector_longdescription", "#product-description", "#product_description",
                     ".product__description", ".product-description", "[itemprop='description']",
                     "[data-product-description]"):
        node = soup.select_one(selector)
        if node is not None and node.get_text(" ", strip=True):
            return node
    heading = soup.find(lambda t: isinstance(t, Tag) and t.name in {"h2", "h3", "h4"}
                        and ("dane techniczne" in _key(t.get_text(" ", strip=True))
                             or "specyfikacja techniczna" in _key(t.get_text(" ", strip=True))))
    if heading is not None:
        fragments = []
        for sib in heading.next_siblings:
            if isinstance(sib, Tag) and sib.name in {"h2", "h3", "h4"}:
                break
            fragments.append(str(sib))
        if fragments:
            return BeautifulSoup("".join(fragments), "html.parser")
    return BeautifulSoup("", "html.parser")


def raw_attribute_rows(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    root = _section(soup)
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def put(label: str, value: str, *, prose: bool = False) -> None:
        label = re.sub(r"\s+", " ", label).strip(" :|\u00a0")
        value = re.sub(r"\s+", " ", value).strip(" :|\u00a0")
        if not label or not value or len(label) > 110 or len(value) > 350:
            return
        if prose:
            # A product description often has marketing bullets like
            # <strong>615 W</strong> — high performance... These are not
            # attribute/value records; the leading dash is meaningful here.
            # Preserve unknown *structured* attributes for future parsers.
            if re.match(r"^[\u2014\u2013]", value) or value.startswith("- "):
                return
            if _key(label) in {"uwaga", "zalety", "korzysci", "zastosowanie", "atuty"}:
                return
        pair = (label, value)
        if pair not in seen:
            found.append({"label": label, "value": value})
            seen.add(pair)

    for tr in root.select("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) == 2:
            put(cells[0].get_text(" ", strip=True), cells[1].get_text(" ", strip=True))

    for dt in root.select("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            put(dt.get_text(" ", strip=True), dd.get_text(" ", strip=True))

    for tag in root.select("p, li"):
        if tag.find_parent("tr") or tag.find_parent("dl"):
            continue
        strong = tag.find(["strong", "b"], recursive=False)
        if strong:
            label = strong.get_text(" ", strip=True)
            line = tag.get_text(" ", strip=True)
            if line.startswith(label):
                put(label, line[len(label):], prose=True)
                continue
        line = tag.get_text(" ", strip=True)
        parts = re.split(r"\s+\|\s+|\s*:\s+", line, maxsplit=1)
        if len(parts) == 2:
            put(*parts, prose=True)
    return found


def _field_for(label: str) -> str | None:
    k = _key(label)
    if not k:
        return None
    if k == "producent": return "manufacturer"
    if k == "model": return "model"
    if "temperaturow" in k:
        if "voc" in k: return "temp_coeff_voc_pct_c"
        if "isc" in k: return "temp_coeff_isc_pct_c"
        if "pmax" in k or "mocy" in k: return "temp_coeff_pmax_pct_c"
        return None
    if k == "noct" or k.startswith("nominalna temperatura pracy ogniwa"): return "noct_c"
    if "liczba ogniw" in k: return "cell_count"
    if "bezpiecznik" in k and "szereg" in k: return "max_series_fuse_a"
    if "wymiar" in k or k.startswith("rozmiar"): return "dimensions_mm"
    if k.startswith(("masa", "waga")): return "mass_kg"
    if "bifacjal" in k or "bifaciality" in k: return "bifaciality_pct"
    if "sprawnosc" in k or "efficiency" in k: return "efficiency_pct"
    if "voc" in k or "obwodu otwartego" in k: return "voc_v"
    if "vmp" in k or "vmpp" in k or ("napiecie" in k and ("mpp" in k or "mocy maks" in k or "punkcie mocy" in k)): return "vmp_v"
    if "isc" in k or "prad zwarciowy" in k: return "isc_a"
    if re.search(r"\bimp\b|\bimpp\b", k) or ("prad" in k and ("mpp" in k or "mocy maks" in k or "punkcie mocy" in k)): return "imp_a"
    if "pmax" in k or "moc znamionowa" in k or "moc maksymalna" in k: return "rated_power_w"
    if "technolog" in k or "typ ogniw" in k or "typ modulu" in k: return "cell_technology"
    if "maksymal" in k and "napieci" in k and "system" in k: return "max_system_voltage_v"
    if "gwarancj" in k:
        if "produkt" in k: return "product_warranty_years"
        if "liniowa" in k or "wydajnos" in k or "mocy" in k: return "performance_warranty_years"
        return "combined_warranty"
    return None


_NUMERIC_UNITS = {
    "rated_power_w": r"\bwp?\b", "efficiency_pct": "%", "voc_v": r"\bv\b",
    "vmp_v": r"\bv\b", "isc_a": r"\ba\b", "imp_a": r"\ba\b",
    "mass_kg": r"\bkg\b", "bifaciality_pct": "%",
    "temp_coeff_pmax_pct_c": r"%\s*/\s*[°º]?c\b",
    "temp_coeff_voc_pct_c": r"%\s*/\s*[°º]?c\b",
    "temp_coeff_isc_pct_c": r"%\s*/\s*[°º]?c\b",
    "max_series_fuse_a": r"\ba\b", "noct_c": r"[°º]c\b",
    "cell_count": None,
    "max_system_voltage_v": r"\bv\b",
    "product_warranty_years": r"\b(?:lat|lata|rok|years?)\b",
    "performance_warranty_years": r"\b(?:lat|lata|rok|years?)\b",
}


def _normalize(rows: list[dict[str, str]]) -> tuple[dict, list[str]]:
    result: dict = {}
    issues: list[str] = []
    for entry in rows:
        field = _field_for(entry["label"])
        if field is None:
            continue
        value = entry["value"]
        if field == "combined_warranty":
            # Combined labels differ too much to infer warranty types reliably.
            issues.append("combined_warranty_needs_review")
            continue
        if field == "dimensions_mm":
            match = _DIMENSIONS.search(value)
            if match:
                parsed = [int(match.group(i)) for i in (1, 2, 3)]
                if all(10 <= x <= 3000 for x in parsed):
                    result[field] = parsed
            continue
        if field in {"manufacturer", "model", "cell_technology"}:
            result.setdefault(field, value)
            continue
        number = _one_number(value, unit=_NUMERIC_UNITS[field])
        if number is None:
            continue
        if field.endswith("warranty_years") or field == "cell_count":
            number = int(number)
        if field in result and result[field] != number:
            issues.append("conflicting_" + field)
            continue
        result[field] = number

    ranges = {"rated_power_w": (100, 900), "efficiency_pct": (10, 30),
              "voc_v": (10, 110), "vmp_v": (10, 100), "isc_a": (1, 40),
              "imp_a": (1, 40), "mass_kg": (5, 60), "bifaciality_pct": (0, 105),
              "max_system_voltage_v": (500, 2000), "max_series_fuse_a": (1, 60),
              "noct_c": (20, 80), "cell_count": (20, 300),
              "product_warranty_years": (1, 50),
              "performance_warranty_years": (1, 50)}
    for k, (low, high) in ranges.items():
        if k in result and not low <= result[k] <= high:
            issues.append("out_of_range_" + k)
            del result[k]
    if "voc_v" in result and "vmp_v" in result and result["voc_v"] <= result["vmp_v"]:
        issues.append("voc_not_above_vmp")
    if "isc_a" in result and "imp_a" in result and result["isc_a"] < result["imp_a"]:
        issues.append("isc_below_imp")
    if all(k in result for k in ("rated_power_w", "vmp_v", "imp_a")):
        estimated = result["vmp_v"] * result["imp_a"]
        if abs(estimated - result["rated_power_w"]) > 0.12 * result["rated_power_w"]:
            issues.append("pmax_vs_vmp_imp_mismatch")
    if "dimensions_mm" in result:
        length, width, _ = result["dimensions_mm"]
        area = length * width / 1_000_000
        result["area_m2"] = round(area, 4)
        if "rated_power_w" in result and area > 0:
            result["power_density_w_m2"] = round(result["rated_power_w"] / area, 2)
            if "efficiency_pct" in result:
                calc_efficiency = result["rated_power_w"] / (1000 * area) * 100
                if abs(calc_efficiency - result["efficiency_pct"]) > 2.0:
                    issues.append("efficiency_vs_area_power_mismatch")
    if not rows:
        issues.append("no_technical_rows")
    return result, sorted(set(issues))


@dataclass(frozen=True)
class PanelSpecSample:
    source_url: str
    page_title: str
    attributes_raw: list[dict[str, str]]
    values: dict
    datasheet_urls: list[str]
    parse_issues: list[str]
    spec_hash: str
    parser_version: str = PARSER_VERSION

    def as_dict(self) -> dict:
        return {"source_url": self.source_url, "page_title": self.page_title,
                "attributes_raw": self.attributes_raw, "values": self.values,
                "datasheet_urls": self.datasheet_urls, "parse_issues": self.parse_issues,
                "spec_hash": self.spec_hash, "parser_version": self.parser_version}


def parse_panel_details(html: str, source_url: str) -> PanelSpecSample:
    if not is_allowed_detail_url(source_url):
        raise ValueError("Only HTTPS Soltech PV product detail pages are supported")
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h1")
    page_title = heading.get_text(" ", strip=True) if heading else (soup.title.get_text(" ", strip=True) if soup.title else "")
    rows = raw_attribute_rows(html)
    normalized, issues = _normalize(rows)
    datasheets: list[str] = []
    # Store *links only*: PDFs are not downloaded and not treated as parsed facts.
    for a in soup.select("a[href]"):
        label = a.get_text(" ", strip=True)
        href = a.get("href", "")
        absolute = urljoin(source_url, href)
        p = urlsplit(absolute)
        if p.scheme != "https" or p.hostname != SITE or not re.search(r"\.pdf(?:$|[?#])", p.path, re.I):
            continue
        if any(token in _key(label + " " + p.path) for token in ("datasheet", "karta katalogowa", "specification")):
            if absolute not in datasheets:
                datasheets.append(absolute)
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if not normalized:
        issues.append("no_normalized_values")
    return PanelSpecSample(source_url, page_title, rows, normalized, datasheets,
                           sorted(set(issues)), checksum)
