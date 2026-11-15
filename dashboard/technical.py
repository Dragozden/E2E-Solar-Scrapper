"""Pure, DB-independent filtering/metrics for the PV technical dashboard.

All technical metrics requiring a model-specific specification are restricted
to is_technical_comparable = TRUE. No inference from incomplete/range data.
"""
from __future__ import annotations

from urllib.parse import urlsplit

import pandas as pd

TECHNICAL_STATUSES = (
    "PASS", "REVIEW", "INCOMPLETE", "NOT_ENRICHED", "POWER_MISMATCH"
)
TECHNICAL_LABELS = {
    "PASS": "Potwierdzona specyfikacja",
    "REVIEW": "Do sprawdzenia",
    "INCOMPLETE": "Niekompletna",
    "NOT_ENRICHED": "Jeszcze nie pobrano",
    "POWER_MISMATCH": "Niezgodna moc",
}
RANGE_FIELDS = ("efficiency_pct", "voc_v", "vmp_v", "isc_a", "imp_a")


def technical_coverage(frame: pd.DataFrame) -> dict[str, int | float]:
    total = len(frame)
    statuses = frame["technical_status"].fillna("")
    counts = {status: int(statuses.eq(status).sum()) for status in TECHNICAL_STATUSES}
    enriched = int(frame["has_specification"].eq(True).sum())
    comparable = int(frame["is_technical_comparable"].eq(True).sum())
    return {
        "total": total,
        "enriched": enriched,
        "comparable": comparable,
        "coverage_pct": round(100.0 * comparable / total, 2) if total else 0.0,
        **counts,
    }


def filter_technical(
    frame: pd.DataFrame,
    *,
    mode: str = "Tylko porównywalne",
    available_only: bool = True,
    search: str = "",
    ranges: dict[str, tuple[float, float]] | None = None,
) -> pd.DataFrame:
    """Apply exact status and numeric filters without changing original ranks.

    Numeric filters exclude NULL-valued products only when the user explicitly
    enables a numeric filter; otherwise non-enriched products stay visible.
    """
    if mode not in ("Tylko porównywalne", "Wszystkie oferty", "Do uzupełnienia"):
        raise ValueError(f"Unknown technical mode: {mode}")
    out = frame.copy()
    if mode == "Tylko porównywalne":
        out = out.loc[out["is_technical_comparable"].eq(True)]
    elif mode == "Do uzupełnienia":
        out = out.loc[~out["is_technical_comparable"].fillna(False)]

    if available_only:
        out = out.loc[out["is_available"].eq(True)]

    if search.strip():
        text = out[["title", "manufacturer", "model"]].fillna("").astype(str)
        contains = text.apply(lambda col: col.str.contains(search.strip(), case=False,
                                                            regex=False, na=False)).any(axis=1)
        out = out.loc[contains]

    for field, bounds in (ranges or {}).items():
        if field not in RANGE_FIELDS:
            raise ValueError(f"Unsupported numeric filter: {field}")
        low, high = bounds
        if low > high:
            raise ValueError(f"Reversed range for {field}")
        values = pd.to_numeric(out[field], errors="coerce")
        out = out.loc[values.between(low, high, inclusive="both")]

    return out.sort_values("overall_rank").reset_index(drop=True)


def technical_comparison(frame: pd.DataFrame, urls: list[str]) -> pd.DataFrame:
    """Compare only qualified specs; preserve the order picked in the UI."""
    if not 2 <= len(urls) <= 5 or len(urls) != len(set(urls)):
        raise ValueError("Choose 2..5 distinct products")
    result = frame.loc[frame["source_url"].isin(urls)
                       & frame["is_technical_comparable"].eq(True)].copy()
    if len(result) != len(urls):
        raise ValueError("A selected product is missing or lacks a qualified spec")
    sort_order = {url: index for index, url in enumerate(urls)}
    result["_comparison_order"] = result["source_url"].map(sort_order)
    return result.sort_values("_comparison_order").drop(columns="_comparison_order").reset_index(drop=True)


def safe_datasheet_url(url: str | None) -> str | None:
    """Show retailer-hosted HTTPS PDFs only, not arbitrary links from raw JSON."""
    if not isinstance(url, str) or not url:
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != "sklepsoltech.pl"
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or not parsed.path.lower().endswith(".pdf")):
            return None
    except ValueError:
        return None
    return url
