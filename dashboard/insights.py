"""Pure price-event analytics used by the dashboard (no database/UI calls)."""

from __future__ import annotations

import pandas as pd


DROP_COLUMNS = [
    "source_url", "title", "observed_at", "previous_observed_at",
    "previous_price_pln", "price_pln", "drop_pln", "drop_pct",
    "power_w", "pln_per_watt", "is_available", "in_latest_snapshot",
]


def price_drop_events(
    history: pd.DataFrame,
    ranking: pd.DataFrame,
    *,
    days: int = 30,
    min_drop_pct: float = 0.0,
    current_only: bool = True,
    available_only: bool = True,
) -> pd.DataFrame:
    """Identify consecutive-observation price cuts, not changes in market averages.

    The lookback is relative to the *latest available history observation*, not
    system time, so snapshots remain interpretable even when the DAG is paused.
    'current_only' means present in the latest ranking snapshot (not necessarily
    a price cut during that latest run). Historical products can be included.
    """
    if days < 1 or min_drop_pct < 0:
        raise ValueError("days >= 1 and min_drop_pct >= 0 are required")
    if history.empty:
        return pd.DataFrame(columns=DROP_COLUMNS)

    cols = ["source_url", "scrape_id", "observed_at", "price_pln", "title", "power_w", "pln_per_watt"]
    valid = history[cols].copy()
    valid["observed_at"] = pd.to_datetime(valid["observed_at"], errors="coerce")
    valid["price_pln"] = pd.to_numeric(valid["price_pln"], errors="coerce")
    valid = valid.dropna(subset=["source_url", "observed_at", "price_pln"])
    valid = valid.loc[valid["source_url"].astype(str).str.strip().ne("") & valid["price_pln"].gt(0)]
    if valid.empty:
        return pd.DataFrame(columns=DROP_COLUMNS)
    valid = valid.sort_values(["source_url", "observed_at", "scrape_id"])
    # dbt Gold already promises one record per (run, URL).
    by_url = valid.groupby("source_url", sort=False)
    valid["previous_price_pln"] = by_url["price_pln"].shift(1)
    valid["previous_observed_at"] = by_url["observed_at"].shift(1)
    valid["drop_pln"] = valid["previous_price_pln"] - valid["price_pln"]
    valid["drop_pct"] = valid["drop_pln"] / valid["previous_price_pln"] * 100

    cutoff = valid["observed_at"].max() - pd.Timedelta(days=days)
    events = valid.loc[
        valid["observed_at"].ge(cutoff)
        & valid["drop_pln"].gt(0)
        & valid["drop_pct"].ge(min_drop_pct)
    ].copy()

    latest = ranking[["source_url", "is_available"]].drop_duplicates("source_url") if not ranking.empty else pd.DataFrame(columns=["source_url", "is_available"])
    latest = latest.rename(columns={"is_available": "latest_available"})
    events = events.merge(latest, on="source_url", how="left")
    events["in_latest_snapshot"] = events["source_url"].isin(latest["source_url"])
    events["is_available"] = events["latest_available"].eq(True).astype(bool)

    if current_only:
        events = events.loc[events["in_latest_snapshot"]]
    if available_only:
        events = events.loc[events["is_available"]]

    return (
        events[DROP_COLUMNS]
        .sort_values(["observed_at", "drop_pct", "source_url"], ascending=[False, False, True])
        .reset_index(drop=True)
    )


def latest_prices_for_comparison(ranking: pd.DataFrame, urls: list[str]) -> pd.DataFrame:
    """Keep current ranking order and return only selected URLs."""
    if ranking.empty or not urls:
        return ranking.iloc[0:0].copy()
    return ranking.loc[ranking["source_url"].isin(urls)].sort_values("overall_rank").copy()
