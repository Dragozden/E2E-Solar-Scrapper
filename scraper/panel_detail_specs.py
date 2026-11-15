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

PARSER_VERSION = "panel-details-v1.2"
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
    # NFKD does not decompose Polish ł/Ł; preserve the letter as ASCII l.
    ascii_text = unicodedata.normalize("NFKD", label.casefold().replace("ł", "l"))
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
    if k == "nmot": return "nmot_c"
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
    "max_series_fuse_a": r"\ba\b", "noct_c": r"[°º]c\b", "nmot_c": r"[°º]c\b",
    "cell_count": None,
    "max_system_voltage_v": r"\bv\b",
    "product_warranty_years": r"\b(?:lat|lata|rok|years?)\b",
    "performance_warranty_years": r"\b(?:lat|lata|rok|years?)\b",
}


# Range and limit qualifiers cannot be treated as exact model specifications.
# The original strings always remain in attributes_raw for later review.
_RANGE_WORDS = re.compile(r"\b(?:od|from|between)\s*[+\-]?\d+(?:[.,]\d+)?(?:\s*%|\s*[wW])?\s*(?:do|to|and|[-–])\s*[+\-]?\d", re.I)
_RANGE_SYMBOLS = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|[wW]p?|[vVaA])?\s*(?:-|–|~|\.\.)\s*[+\-]?\d+(?:[.,]\d+)?")
_UPPER_BOUND = re.compile(r"^\s*(?:do|up to|at most|maksymalnie|nie więcej niż|<=|≤|<)\s*[+\-]?\d", re.I)
_LOWER_BOUND = re.compile(r"^\s*(?:od|co najmniej|at least|>=|≥|>)\s*[+\-]?\d", re.I)
_GROUPED_TEMP = re.compile(r"\b(pmax|voc|isc)\b\s*[:=]?\s*([+\-]?\d+(?:[.,]\d+)?)\s*%\s*/\s*[°º]?c\b", re.I)
_WARRANTY_YEARS = re.compile(r"(\d{1,2})\s*(?:lat|lata|rok|years?)\b", re.I)


def _numeric_qualifier_issue(value: str, field: str) -> str | None:
    """Refuse a single number when retailer text describes a range/bound.

    A tolerance like `80% ±5%` is not a range of different module variants:
    80 is a stated nominal value, which is kept. `45°C ±2°C` likewise.
    """
    if _UPPER_BOUND.search(value):
        return "upper_bound_not_exact_" + field
    if _RANGE_WORDS.search(value) or _RANGE_SYMBOLS.search(value):
        return "range_not_exact_" + field
    if _LOWER_BOUND.search(value):
        return "lower_bound_not_exact_" + field
    return None


def _warranty_parts(value: str) -> dict[str, int]:
    """Parse only unambiguous warranty subject phrases near each duration.

    '12 lat gwarancji materiałowej, 30 lat gwarancji mocy' -> two fields.
    '30 lat liniowej gwarancji na moc' -> only performance warranty.
    '12 lat i 30 lat' is deliberately unresolved.
    """
    matches = list(_WARRANTY_YEARS.finditer(value))
    found: dict[str, int] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(value)
        subject = _key(value[m.end():end].split("(")[0])
        # Require explicit subject, not generic claim "warranty 12 years".
        if re.search(r"\b(moc|mocy|wydajnosc|wydajnosci)\b", subject):
            field = "performance_warranty_years"
        elif re.search(r"\b(produkt|produktu|produktowej|materialowa|materialowej|materialu|materialna|materialnej)\b", subject):
            field = "product_warranty_years"
        else:
            continue
        number = int(m.group(1))
        if field in found and found[field] != number:
            return {}
        found[field] = number
    return found


def _grouped_temp_coefficients(value: str) -> dict[str, float]:
    mapping = {"pmax": "temp_coeff_pmax_pct_c", "voc": "temp_coeff_voc_pct_c",
               "isc": "temp_coeff_isc_pct_c"}
    result: dict[str, float] = {}
    for m in _GROUPED_TEMP.finditer(value):
        field = mapping[m.group(1).lower()]
        v = float(m.group(2).replace(",", "."))
        if field in result and result[field] != v:
            return {}
        result[field] = v
    return result


def _put_value(result: dict, issues: list[str], field: str, value: object) -> None:
    if field in result and result[field] != value:
        issues.append("conflicting_" + field)
    else:
        result[field] = value


def sample_quality(values: dict, issues: list[str]) -> dict:
    """Conservative quality gate for publishing numerical model comparisons.

    Bronze may preserve partial raw data, but this manual pilot's --write is
    restricted to full electrical specifications until a reviewed partial-data
    policy and Silver quality model exist.
    """
    required = ("rated_power_w", "voc_v", "vmp_v", "isc_a", "imp_a")
    missing = sorted(set(required) - values.keys())
    blocking = sorted(issue for issue in issues if issue.startswith((
        "conflicting_", "out_of_range_", "voc_not_above_vmp",
        "isc_below_imp", "pmax_vs_vmp_imp_mismatch",
        "efficiency_vs_area_power_mismatch", "no_technical_rows",
        "no_normalized_values",
    )))
    return {"status": "PASS" if not missing and not blocking else "INCOMPLETE",
            "missing_core_fields": missing, "blocking_issues": blocking,
            "review_issues": sorted(set(issues) - set(blocking))}


def _normalize(rows: list[dict[str, str]]) -> tuple[dict, list[str]]:
    result: dict = {}
    issues: list[str] = []
    for entry in rows:
        label = entry["label"]
        value = entry["value"]
        if _key(label) in {"wspolczynniki temperaturowe", "temperature coefficients"}:
            components = _grouped_temp_coefficients(value)
            if not components:
                issues.append("grouped_temperature_coefficients_needs_review")
            for k, v in components.items():
                _put_value(result, issues, k, v)
            continue
        field = _field_for(label)
        if field is None:
            continue
        if field == "combined_warranty":
            parts = _warranty_parts(value)
            if not parts:
                issues.append("combined_warranty_needs_review")
            for k, v in parts.items():
                _put_value(result, issues, k, v)
            continue
        if field == "dimensions_mm":
            match = _DIMENSIONS.search(value)
            if match:
                parsed = [int(match.group(i)) for i in (1, 2, 3)]
                if all(10 <= x <= 3000 for x in parsed):
                    result[field] = parsed
            continue
        if field in {"manufacturer", "model", "cell_technology"}:
            if field == "cell_technology":
                # Separate a clearly marked marketing sentence from the actual
                # technology. Preserve the full source phrase in attributes_raw.
                tech = re.split(r"\s+[–—]\s+", value, maxsplit=1)[0].strip()
                result.setdefault(field, tech)
                cell_match = re.search(r"\b(\d{2,3})\s*ogniw(?:a)?\b", tech, re.I)
                if cell_match:
                    _put_value(result, issues, "cell_count", int(cell_match.group(1)))
            else:
                result.setdefault(field, value)
            continue
        qualifier_issue = _numeric_qualifier_issue(value, field)
        if qualifier_issue:
            issues.append(qualifier_issue)
            continue
        number = _one_number(value, unit=_NUMERIC_UNITS[field])
        if number is None:
            continue
        if field.endswith("warranty_years") or field == "cell_count":
            number = int(number)
        _put_value(result, issues, field, number)

    ranges = {"rated_power_w": (100, 900), "efficiency_pct": (10, 30),
              "voc_v": (10, 110), "vmp_v": (10, 100), "isc_a": (1, 40),
              "imp_a": (1, 40), "mass_kg": (5, 60), "bifaciality_pct": (0, 105),
              "max_system_voltage_v": (500, 2000), "max_series_fuse_a": (1, 60),
              "noct_c": (20, 80), "nmot_c": (20, 80), "cell_count": (20, 300),
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
    canonical = json.dumps({"parser_version": PARSER_VERSION, "raw": rows,
                            "normalized": normalized, "issues": sorted(set(issues))},
                           ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if not normalized:
        issues.append("no_normalized_values")
    return PanelSpecSample(source_url, page_title, rows, normalized, datasheets,
                           sorted(set(issues)), checksum)
