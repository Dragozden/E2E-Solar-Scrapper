"""Independent Bronze/Gold freshness check, invoked by the solar_watchdog DAG.

No scraping, SQL writes, or dbt builds. Scrape timestamps are naive UTC in the
current Docker runtime (scraper.load uses datetime.now() without tzinfo).
If changing the container timezone, migrate timestamp semantics first.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

LATEST_SNAPSHOT_SQL = """
WITH latest_run AS (
    SELECT scrape_run_id, finished_at, products_count
    FROM bronze.scrape_runs
    WHERE status = 'SUCCESS' AND finished_at IS NOT NULL
    ORDER BY finished_at DESC NULLS LAST
    LIMIT 1
)
SELECT r.scrape_run_id, r.finished_at, r.products_count,
       COUNT(p.scrape_id) AS actual_count,
       COUNT(p.scrape_id) FILTER (
           WHERE p.source_url IS NULL OR TRIM(p.source_url) = ''
       ) AS missing_urls,
       COUNT(p.scrape_id) FILTER (
           WHERE p.source_url IS NOT NULL AND TRIM(p.source_url) <> ''
       ) - COUNT(DISTINCT NULLIF(TRIM(p.source_url), '')) AS duplicate_urls
FROM latest_run r
LEFT JOIN bronze.panel_scrape_raw p ON r.scrape_run_id = p.scrape_run_id
GROUP BY r.scrape_run_id, r.finished_at, r.products_count;
"""


class DataHealthError(RuntimeError):
    """A pipeline snapshot is stale or invalid."""


def assert_snapshot_healthy(
    snapshot: tuple | None,
    *,
    now_utc: datetime,
    max_age_hours: float = 30.0,
) -> float:
    """Return snapshot age in hours or raise DataHealthError.

    snapshot: (run_id, finished_at, expected_count, actual_count,
               missing_urls, duplicate_urls)
    """
    if max_age_hours <= 0:
        raise ValueError("max_age_hours must be positive")
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    if snapshot is None:
        raise DataHealthError("No completed SUCCESS scrape run in Bronze")

    run_id, finished_at, expected, actual, missing, duplicates = snapshot
    if finished_at is None:
        raise DataHealthError(f"Run {run_id}: missing finished_at")
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    age_h = (now_utc.astimezone(timezone.utc) - finished_at.astimezone(timezone.utc)).total_seconds() / 3600
    if age_h < -0.1:
        raise DataHealthError(f"Run {run_id}: finished_at is in the future by {-age_h:.1f} h")
    if age_h > max_age_hours:
        raise DataHealthError(f"Run {run_id}: snapshot is {age_h:.1f} h old (> {max_age_hours:g} h)")
    if expected is None or expected <= 0 or actual != expected or missing != 0 or duplicates != 0:
        raise DataHealthError(
            f"Run {run_id}: invalid Bronze: expected={expected}, actual={actual}, "
            f"missing_urls={missing}, duplicate_urls={duplicates}"
        )
    return age_h


def main() -> None:
    from scraper.load import get_connection  # postpone DB dependency to runtime

    max_age_hours = float(os.getenv("SOLAR_MAX_SNAPSHOT_AGE_HOURS", "30"))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(LATEST_SNAPSHOT_SQL)
            snapshot = cur.fetchone()
            age_h = assert_snapshot_healthy(
                snapshot,
                now_utc=datetime.now(timezone.utc),
                max_age_hours=max_age_hours,
            )
            cur.execute("SELECT COUNT(*) FROM gold.current_panel_ranking")
            gold_count = cur.fetchone()[0]
            if not gold_count:
                raise DataHealthError("Gold current_panel_ranking is empty")

    print(
        f"WATCHDOG PASS: latest Bronze SUCCESS age={age_h:.1f}h, "
        f"panels={snapshot[3]}, Gold rows={gold_count}",
        flush=True,
    )


if __name__ == "__main__":
    main()
