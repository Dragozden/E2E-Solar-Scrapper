"""Pure data transformations for the Streamlit dashboard.

No Streamlit imports and no database access, so these functions can be
unit-tested in isolation.
"""

from __future__ import annotations

import pandas as pd


def filter_ranking(
    ranking: pd.DataFrame,
    *,
    availability: str = "Wszystkie",
    search: str = "",
    min_power: int | None = None,
    max_power: int | None = None,
    max_pln_per_watt: float | None = None,
) -> pd.DataFrame:
    """Filter the latest snapshot without changing its original dbt ranking."""
    filtered = ranking.copy()

    if availability == "Dostępne":
        filtered = filtered.loc[filtered["is_available"].eq(True)]
    elif availability == "Niedostępne":
        filtered = filtered.loc[filtered["is_available"].eq(False)]
    elif availability != "Wszystkie":
        raise ValueError(f"Nieznany filtr dostępności: {availability}")

    if search.strip():
        # Escape/regex=False is intentional: product names may contain [] / + etc.
        filtered = filtered.loc[
            filtered["title"].str.contains(search.strip(), case=False, regex=False, na=False)
        ]
    if min_power is not None:
        filtered = filtered.loc[filtered["power_w"] >= min_power]
    if max_power is not None:
        filtered = filtered.loc[filtered["power_w"] <= max_power]
    if max_pln_per_watt is not None:
        filtered = filtered.loc[filtered["pln_per_watt"] <= max_pln_per_watt]

    return filtered.sort_values("overall_rank").reset_index(drop=True)


def available_metrics(ranking: pd.DataFrame) -> dict[str, float | int | None]:
    """Global KPIs refer to the latest run, regardless of display filters."""
    available = ranking.loc[ranking["is_available"].eq(True)]
    per_watt = pd.to_numeric(available["pln_per_watt"], errors="coerce").dropna()

    return {
        "total": len(ranking),
        "available": len(available),
        "min_pln_per_watt": float(per_watt.min()) if not per_watt.empty else None,
        "avg_pln_per_watt": float(per_watt.mean()) if not per_watt.empty else None,
    }


def latest_product_labels(history: pd.DataFrame) -> dict[str, str]:
    """One label per product URL, using its latest historical name."""
    if history.empty:
        return {}
    last_seen = (
        history.dropna(subset=["source_url"])
        .sort_values(["observed_at", "scrape_id"])
        .drop_duplicates("source_url", keep="last")
    )
    return dict(zip(last_seen["source_url"], last_seen["title"]))


def product_history(history: pd.DataFrame, source_url: str) -> pd.DataFrame:
    """Chronological observations for the selected product only."""
    result = history.loc[history["source_url"].eq(source_url)].copy()
    result["observed_at"] = pd.to_datetime(result["observed_at"], errors="coerce")
    return result.dropna(subset=["observed_at"]).sort_values(
        ["observed_at", "scrape_id"]
    ).reset_index(drop=True)


def product_summary(product: pd.DataFrame) -> dict[str, float | int | None]:
    """Compare the first and last valid prices, NOT average historical records."""
    valid = product.dropna(subset=["price_pln"])
    if valid.empty:
        return {"observations": len(product), "current_price": None, "first_price": None,
                "difference_pln": None, "difference_pct": None}

    first = float(valid.iloc[0]["price_pln"])
    current = float(valid.iloc[-1]["price_pln"])
    delta = current - first
    return {
        "observations": len(product),
        "current_price": current,
        "first_price": first,
        "difference_pln": delta,
        "difference_pct": (delta / first * 100) if first > 0 else None,
    }


def latest_observation_per_day(history: pd.DataFrame) -> pd.DataFrame:
    """Optional per-day reduction for UI only; preserve full raw history elsewhere."""
    if history.empty:
        return history.copy()
    chronological = history.sort_values(["observed_at", "scrape_id"]).copy()
    chronological["date"] = pd.to_datetime(chronological["observed_at"]).dt.date
    return chronological.drop_duplicates("date", keep="last").reset_index(drop=True)
