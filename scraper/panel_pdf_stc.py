"""Strict, offline-only STC table candidate extraction from PDF text rows.

This module intentionally does NOT scrape, write to PostgreSQL, or claim a
manufacturer match solely from identical wattage. PDF extraction is lossy:
outputs are human-review candidates with page and SHA-256 evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Sequence

METRICS = ("rated_power_w", "voc_v", "isc_a", "vmp_v", "imp_a", "efficiency_pct")
FIELD_PATTERNS = {
    "rated_power_w": (r"\bpmax\b", r"\brated power\b", r"\bmaximum power\b", r"moc znamionowa", r"moc maksymalna"),
    "voc_v": (r"\bvoc\b", r"open circuit voltage", r"napiecie obwodu otwartego"),
    "isc_a": (r"\bisc\b", r"short circuit current", r"prad zwarciowy", r"prad zwarcia"),
    "vmp_v": (r"\bvmp\b", r"\bvmpp\b", r"\bumpp\b", r"voltage at maximum power", r"maximum power voltage", r"napiecie mocy maksymalnej", r"napiecie przy mocy maksymalnej"),
    "imp_a": (r"\bimp\b", r"\bimpp\b", r"current at maximum power", r"maximum power current", r"prad mocy maksymalnej"),
    "efficiency_pct": (r"module efficiency", r"sprawnosc modulu"),
}
# Avoid picking values from 'rear gain' and NMOT tables, or the spec's labels.
VALUES = re.compile(r"(?<![\w])\d{1,4}(?:[.,]\d{1,4})?(?![\w])")
HEADING_STC = re.compile(r"(?i)(?:electrical|elektryczn|parametr).*\bSTC\b|\bSTC\b.*(?:electrical|elektryczn|parametr)")
OTHER_SECTIONS = re.compile(
    r"(?i)\bNMOT\b|\bNOCT\b|\bBNPI\b|\brear\s+side\b|\brear\s+power\b|"
    r"przyrost(?:em)?\s+mocy|\bgain\b|\bwarranty\b|\bgwarancj|\bmechanic|"
    r"\btemperatur|\boperating parameters\b|\bdane mechaniczne\b"
)


def normalize(text: str) -> str:
    text = text.replace("ł", "l").replace("Ł", "L")
    plain = unicodedata.normalize("NFKD", text)
    return "".join(c for c in plain if not unicodedata.combining(c)).lower()


def row_type(text: str) -> str | None:
    flat = normalize(text)
    for field in ("voc_v", "isc_a", "vmp_v", "imp_a", "efficiency_pct", "rated_power_w"):
        patterns = FIELD_PATTERNS[field]
        if any(re.search(p, flat) for p in patterns):
            return field
    return None


def _numbers_after_label(line: str, metric: str) -> list[float]:
    """Parse only the *values* after a recognized unit/label boundary.

    Accept e.g. 'Open Circuit Voltage: Voc [V] 39.88 40.06 40.24' or
    'Napiecie obwodu otwartego-Voc(V) | 39,88 | 40,06'.
    Reject lines without explicit units, to avoid guessing where label ends.
    """
    flat = normalize(line)
    if metric == "rated_power_w":
        start = re.search(r"(?:\[w(?:p)?\]|\(w(?:p)?\))\s*", flat)
    elif metric in ("voc_v", "vmp_v"):
        start = re.search(r"(?:\[v\]|\(v\))\s*", flat)
    elif metric in ("isc_a", "imp_a"):
        start = re.search(r"(?:\[a\]|\(a\))\s*", flat)
    else:
        start = re.search(r"(?:\[%\]|\(%\)|\bη\s*\[%\]|\bη\s*\(%\))\s*", flat)
    if start is None:
        return []
    suffix = line[start.end():]
    # Label suffix must only contain values, spaces, or column bars. Avoid a
    # split line where a later section's unrelated measurement got appended.
    if re.search(r"[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]", suffix):
        return []
    return [float(m.group().replace(",", ".")) for m in VALUES.finditer(suffix)]


@dataclass(frozen=True)
class StcCandidate:
    page: int
    power_w: int
    variant_column: int
    model_family: str
    values: dict[str, float]
    warning: str

    def as_dict(self) -> dict:
        return {
            "page": self.page,
            "power_w": self.power_w,
            "variant_column_zero_based": self.variant_column,
            "model_family": self.model_family,
            "values": self.values,
            "warning": self.warning,
        }


def family_token(model: str) -> str:
    """Return a conservative *family hint*, never a verified exact model."""
    txt = re.sub(r"[^A-Za-z0-9-]", "", model).upper()
    m = re.search(r"^(TWMN[HD]-\d{2}HD|RSM\d+-\d+)", txt)
    if m:
        return m.group(1)
    # Last chance: no claim of an exact match, useful only for review.
    m = re.match(r"[A-Z]{2,10}[-A-Z0-9]{2,12}", txt)
    return m.group(0) if m else ""


def find_stc_candidates(lines: Sequence[str], target_power: int, *, page: int,
                        model_family: str = "") -> list[StcCandidate]:
    """Find a complete STC table block. Strictly reject ambiguous layouts."""
    if not 100 <= target_power <= 900:
        raise ValueError("Expected panel nominal power in 100..900 W")
    candidates: list[StcCandidate] = []
    head_indexes = [i for i, line in enumerate(lines) if HEADING_STC.search(normalize(line))]
    for begin in head_indexes:
        end = next((i for i in range(begin + 1, len(lines))
                    if OTHER_SECTIONS.search(normalize(lines[i]))), len(lines))
        segment = lines[begin + 1:end]
        collected: dict[str, list[float]] = {}
        ambiguous = False
        for line in segment:
            metric = row_type(line)
            if metric is None:
                continue
            values = _numbers_after_label(line, metric)
            if not values:
                continue
            if metric in collected and values != collected[metric]:
                ambiguous = True
                break
            collected[metric] = values
        if ambiguous or any(name not in collected for name in METRICS[:5]):
            continue
        powers = collected["rated_power_w"]
        if not all(int(p) == p for p in powers):
            continue
        positions = [i for i, power in enumerate(powers) if abs(power - target_power) < 1e-9]
        if len(positions) != 1:
            continue
        if not all(len(collected[k]) == len(powers) for k in METRICS[:5]):
            continue
        pos = positions[0]
        chosen = {name: values[pos] for name, values in collected.items()
                  if name in METRICS and len(values) == len(powers)}
        if not (chosen["voc_v"] > chosen["vmp_v"] > 0
                and chosen["isc_a"] >= chosen["imp_a"] > 0):
            continue
        if abs(chosen["vmp_v"] * chosen["imp_a"] - target_power) > 0.12 * target_power:
            continue
        if "efficiency_pct" in chosen and not (10 <= chosen["efficiency_pct"] <= 30):
            continue
        candidates.append(StcCandidate(
            page=page, power_w=target_power, variant_column=pos,
            model_family=model_family, values=chosen,
            warning="CANDIDATE_ONLY: verify model family, PDF revision, page and STC column manually",
        ))
    # Refuse if multiple valid-looking STC tables exist in one PDF/page.
    return candidates if len(candidates) == 1 else []
