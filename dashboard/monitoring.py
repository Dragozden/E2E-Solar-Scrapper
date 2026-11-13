"""Classify scrape quality using immutable run history. No UI/DB dependencies."""

from __future__ import annotations

import pandas as pd


def evaluate_runs(runs: pd.DataFrame, *, drop_warning_pct: float = 30.0) -> pd.DataFrame:
    """Quality state vs volume anomaly are separate signals.

    Successful runs must have the right count, nonempty URLs, and unique URLs.
    A catalog contraction versus the *previous SUCCESS* is a WARNING only.
    Failed/running runs are not treated as proof that Gold is corrupt.
    """
    if not 0 <= drop_warning_pct <= 100:
        raise ValueError("drop_warning_pct must be between 0 and 100")

    result = runs.copy()
    for col in ["expected_count", "actual_count", "missing_urls", "duplicate_urls"]:
        if col not in result:
            result[col] = pd.Series(dtype="float64")
        result[col] = pd.to_numeric(result[col], errors="coerce")
    if "started_at" in result:
        result["started_at"] = pd.to_datetime(result["started_at"], errors="coerce")
    if "finished_at" in result:
        result["finished_at"] = pd.to_datetime(result["finished_at"], errors="coerce")
    if result.empty:
        result["quality_status"] = pd.Series(dtype="object")
        result["drop_pct_vs_previous_success"] = pd.Series(dtype="float64")
        result["volume_warning"] = pd.Series(dtype="bool")
        return result

    result = result.sort_values(["started_at", "scrape_run_id"]).reset_index(drop=True)
    statuses = []
    drops = []
    warnings = []
    previous_success_unique = None

    for _, run in result.iterrows():
        status = str(run["status"])
        expected, actual = run["expected_count"], run["actual_count"]
        missing, nonunique = run["missing_urls"], run["duplicate_urls"]
        count_valid = pd.notna(expected) and pd.notna(actual) and expected > 0 and expected == actual
        valid = count_valid and missing == 0 and nonunique == 0

        if status == "SUCCESS":
            statuses.append("PASS" if valid else "FAIL")
            # Unique count is actual minus repeated/missing URLs.
            unique = actual - missing - nonunique if pd.notna(actual) and pd.notna(missing) and pd.notna(nonunique) else None
            decline = (
                (previous_success_unique - unique) / previous_success_unique * 100
                if unique is not None and previous_success_unique is not None and previous_success_unique > 0
                else None
            )
            drops.append(decline)
            warnings.append(bool(decline is not None and decline >= drop_warning_pct))
            if unique is not None:
                previous_success_unique = unique
        else:
            statuses.append(status)
            drops.append(None)
            warnings.append(False)
    result["quality_status"] = statuses
    result["drop_pct_vs_previous_success"] = drops
    result["volume_warning"] = warnings
    return result.sort_values(["started_at", "scrape_run_id"], ascending=[False, False]).reset_index(drop=True)
