"""Strict, offline-only STC table candidate extraction from PDF text rows.

This module intentionally does NOT scrape, write to PostgreSQL, or claim a
manufacturer match solely from identical wattage. PDF extraction is lossy:
outputs are human-review candidates with page and SHA-256 evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Sequence, Mapping

METRICS = ("rated_power_w", "voc_v", "isc_a", "vmp_v", "imp_a", "efficiency_pct")
FIELD_PATTERNS = {
    "rated_power_w": (r"\bpmax\b", r"\brated power\b", r"\bmaximum power\b", r"moc znamionowa", r"moc maksymalna"),
    "voc_v": (r"\bvoc\b", r"open circuit voltage", r"napiecie obwodu otwartego"),
    "isc_a": (r"\bisc\b", r"\blsc\b", r"short circuit current", r"prad zwarciowy", r"prad zwarcia"),
    "vmp_v": (r"\bvmp\b", r"\bvmpp\b", r"\bumpp\b", r"voltage at maximum power", r"maximum power voltage", r"napiecie mocy maksymalnej", r"napiecie przy mocy maksymalnej"),
    "imp_a": (r"\bimp\b", r"\blmp\b", r"\bimpp\b", r"current at maximum power", r"maximum power current", r"prad mocy maksymalnej"),
    "efficiency_pct": (r"module efficiency", r"sprawnosc modulu", r"wydajnosc modulu"),
}
# Avoid picking values from 'rear gain' and NMOT tables, or the spec's labels.
VALUES = re.compile(r"(?<![\w])\d{1,4}(?:[.,]\d{1,4})?(?![\w])")
HEADING_STC = re.compile(r"(?i)(?:electrical|elektryczn|parametr).*\bSTC\b|\bSTC\b.*(?:electrical|elektryczn|parametr)")
OTHER_SECTIONS = re.compile(
    r"(?i)\bN\s*[-. ]?\s*MOT\b|\bNOCT\b|\bBNPI\b|\brear\s+side\b|\brear\s+power\b|"
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


# PDF 11.5a.1: geometry-aware conservative fallback for production datasheets.
# Real PDFs may split the STC title into separate text fragments and place
# electrical row values in independent text boxes. We still require explicit
# STC header, a unique exact Pmax column, aligned rows, and physics checks.
_STC_TOKEN = re.compile(r"\bstc\b")
_ELECTRICAL_HEADING = re.compile(r"elektryczn|charakterystyk|electrical|elektrisch")
_NMOT_SECTION = re.compile(r"\b(?:n[\s.\-]*mot|noct|bnpi)\b")
_REAR_SECTION = re.compile(
    r"\b(?:tylna\s+strona|tylnej\s+strony|rear\s+side|rear\s+gain|"
    r"rear\s+power|bifacial\s+gain)\b"
)


def _is_following_section_heading(text: str) -> bool:
    """Detect an *explicit* subsequent section boundary, not arbitrary data.

    A Polish datasheet can render NMOT as '(N MOT)' (separate PDF words)
    and the rear-side section as 'CHARAKTERYSTYKA ELEKTRYCZNA TYLNA STRONA
    MODULU'. Treat both as boundaries BEFORE collecting rows. A numerical
    field must never be borrowed from the NMOT or backside-gain sections.
    """
    flat = normalize(text)
    return bool(_NMOT_SECTION.search(flat) or _REAR_SECTION.search(flat))
_SPATIAL_NUMBER = re.compile(r"[+\-]?\d{1,4}(?:[.,]\d{1,4})?")
_SPATIAL_LABELS = {
    "rated_power_w": "Maximum Power: Pmax [W]",
    "voc_v": "Open Circuit Voltage: Voc [V]",
    "isc_a": "Short Circuit Current: Isc [A]",
    "vmp_v": "Voltage at Maximum Power: Vmp [V]",
    "imp_a": "Current at Maximum Power: Imp [A]",
    "efficiency_pct": "Module Efficiency [%]",
}


def _word_rows(words: Sequence[Mapping], *, tolerance: float = 3.2) -> list[dict]:
    """Group pdfplumber words by visual line, not lossy extracted text order."""
    rows: list[dict] = []
    for w in sorted(words, key=lambda w: (float(w["top"]), float(w["x0"]))):
        if not isinstance(w.get("text"), str) or not w["text"].strip():
            continue
        top = float(w["top"])
        matched = next((r for r in reversed(rows[-5:])
                        if abs(r["top"] - top) <= tolerance), None)
        if matched is None:
            matched = {"top": top, "bottom": float(w.get("bottom", top)), "words": []}
            rows.append(matched)
        matched["words"].append(w)
        matched["bottom"] = max(matched["bottom"], float(w.get("bottom", top)))
    for row in rows:
        row["words"].sort(key=lambda w: float(w["x0"]))
        row["text"] = " ".join(str(w["text"]) for w in row["words"])
    return sorted(rows, key=lambda r: r["top"])


def spatial_stc_anchors(words: Sequence[Mapping], *, page_width: float) -> list[dict]:
    """Locate 'STC' heading by neighboring words, including a split heading.

    A footnote 'STC: 1000W/m2' is deliberately not a heading.
    """
    rows = _word_rows(words)
    anchors = []
    for i, row in enumerate(rows):
        line = normalize(row["text"])
        if not _STC_TOKEN.search(line):
            continue
        # Heading may use two visual text lines (graphic PDF font placement).
        context = " ".join(normalize(r["text"]) for r in rows[max(0, i-2):i+1]
                           if abs(r["top"] - row["top"]) <= 30)
        if not _ELECTRICAL_HEADING.search(context):
            continue
        tokens = [w for w in row["words"] if _STC_TOKEN.search(normalize(str(w["text"])))]
        if not tokens:
            continue
        word = tokens[-1]
        # Use the electrical heading origin, not the STC token position:
        # the title can share a visual line with an unrelated drawing label.
        heading_words = [w for w in row["words"]
                         if float(w["x0"]) <= float(word["x0"])
                         and _ELECTRICAL_HEADING.search(normalize(str(w["text"])))]
        start = min((float(w["x0"]) for w in heading_words), default=None)
        anchors.append({"top": row["top"], "bottom": row["bottom"],
                        "x0": float(word["x0"]), "heading_start": start,
                        "text": row["text"]})
    return anchors


def spatial_stc_candidate(words: Sequence[Mapping], target_power: int, *, page: int,
                          page_width: float, model_family: str = "") -> tuple[list[StcCandidate], list[str]]:
    """Extract STC values from aligned visual rows; fail closed on ambiguity.

    All data originate from the bounded half-page STC region. Never guess
    missing values from a neighboring power variant, NMOT, rear gain, or
    a section without an explicit electrical STC heading.
    """
    anchors = spatial_stc_anchors(words, page_width=page_width)
    diagnostics: list[str] = []
    if not anchors:
        return [], ["NO_SPATIAL_STC_HEADING"]
    all_found: list[StcCandidate] = []
    for head in anchors:
        # The STC heading is normally in a half-width product-spec column.
        # Restrict all values to that column so a right-side warranty graph
        # cannot contribute a similarly positioned number.
        start = head.get("heading_start")
        if start is not None and start >= page_width * 0.28:
            # Some datasheets give the drawing ~38% and the STC table the
            # remaining ~62%. Anchor the left edge to the electrical label.
            left, right = max(0.0, start - 8.0), page_width
        else:
            left = 0.0 if head["x0"] < page_width * 0.58 else page_width * 0.49
            right = min(page_width, left + page_width * 0.53)
        column = [w for w in words if left <= float(w["x0"]) < right]
        # Scan VISUAL LINES for the next section rather than individual words:
        # 'N MOT' is often split into two PDF text objects, so word-level
        # matching can miss the boundary and read the next electrical table.
        # Also stop at the rear-side gain section, which may carry a second
        # complete set of Voc/Isc/Vmp/Imp without the letters NMOT.
        all_column_rows = _word_rows(column)
        following_headers = [r for r in all_column_rows
                             if r["top"] > head["bottom"] + 12
                             and (_is_following_section_heading(r["text"])
                                  or re.match(r"^[* ]*stc\s*:", normalize(r["text"])))]
        # A section heading may be split across nearby rows; check a short
        # window while anchoring the boundary to the earliest involved row.
        for before, after in zip(all_column_rows, all_column_rows[1:]):
            if not (before["top"] > head["bottom"] + 12
                    and 0 <= after["top"] - before["bottom"] <= 15):
                continue
            if (not _is_following_section_heading(before["text"])
                    and not _is_following_section_heading(after["text"])
                    and _is_following_section_heading(before["text"] + " " + after["text"])):
                following_headers.append(before)
        limit = (min(r["top"] for r in following_headers) - 3
                 if following_headers else head["bottom"] + 200)
        region = [w for w in column if float(w["top"]) >= head["bottom"] - 1
                  and float(w["top"]) <= limit]
        rows = _word_rows(region)
        fields: dict[str, list[tuple[float, float]]] = {}
        duplicates: set[str] = set()
        for row in rows:
            field = row_type(row["text"])
            if field is None:
                continue
            numbers: list[tuple[float, float]] = []
            for w in row["words"]:
                value_text = str(w["text"]).strip().strip("|;:")
                if not _SPATIAL_NUMBER.fullmatch(value_text):
                    continue
                numbers.append((float(w["x0"] + w.get("x1", w["x0"])) / 2,
                                float(value_text.replace(",", "."))))
            if not numbers:
                continue
            if field in fields:
                duplicates.add(field)
            else:
                fields[field] = numbers
        if duplicates:
            diagnostics.append("DUPLICATE_METRIC_ROWS:" + ",".join(sorted(duplicates)))
            continue
        required = METRICS[:5]
        if any(name not in fields for name in required):
            diagnostics.append("MISSING_SPATIAL_METRICS:" + ",".join(x for x in required if x not in fields))
            continue
        power_cols = fields["rated_power_w"]
        powers = [value for _, value in power_cols]
        if not (2 <= len(powers) <= 12 and all(100 <= v <= 900 and v == int(v) for v in powers)):
            diagnostics.append("INVALID_POWER_COLUMNS")
            continue
        if sum(p == target_power for p in powers) != 1:
            diagnostics.append("TARGET_POWER_NOT_UNIQUE")
            continue
        if any(len(fields[name]) != len(powers) for name in required):
            diagnostics.append("INCONSISTENT_SPATIAL_COLUMN_COUNTS")
            continue
        # Do not make a candidate unless all current/voltage/power rows have
        # the same x-position columns. PDF extraction can otherwise silently
        # reorder or drop a column.
        if any(any(abs(actual[0] - power_cols[i][0]) > 13.0 for i, actual in enumerate(fields[name]))
               for name in required if name != "rated_power_w"):
            diagnostics.append("MISALIGNED_SPATIAL_COLUMNS")
            continue
        if "efficiency_pct" in fields and (len(fields["efficiency_pct"]) != len(powers)
                 or any(abs(actual[0] - power_cols[i][0]) > 13.0
                        for i, actual in enumerate(fields["efficiency_pct"]))):
            # Efficiency is optional; an ambiguous efficiency row is omitted.
            fields.pop("efficiency_pct")
        reconstructed = ["ELECTRICAL CHARACTERISTICS (STC)"]
        for field in METRICS:
            if field in fields:
                values = " ".join(f"{val:g}" for _, val in fields[field])
                # Explicit fixed units are safe: they come from detected metric
                # names and only support the already-present named row.
                reconstructed.append(f"{_SPATIAL_LABELS[field]} {values}")
        found = find_stc_candidates(reconstructed, target_power, page=page,
                                    model_family=model_family)
        if not found:
            diagnostics.append("PHYSICS_OR_STC_VALIDATION_FAILED")
            continue
        all_found.extend(found)
        diagnostics.append("SPATIAL_STC_COLUMNS_VALIDATED")
    # Never choose arbitrarily between multiple matches.
    if len(all_found) != 1:
        return [], diagnostics + (["MULTIPLE_SPATIAL_CANDIDATES"] if all_found else [])
    return all_found, diagnostics
