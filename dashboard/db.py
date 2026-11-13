"""Read-only PostgreSQL access to dbt Gold views.

This module uses the same .env variables as the existing scraper and dbt.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

SQL_RANKING = """
SELECT overall_rank, scrape_run_id::text AS scrape_run_id, title,
       source_url, price_pln, power_w, is_available, scraped_at,
       pln_per_watt, watt_per_pln, price_category
FROM gold.current_panel_ranking
ORDER BY overall_rank;
"""

SQL_HISTORY = """
SELECT scrape_id, scrape_run_id::text AS scrape_run_id, title,
       source_url, price_pln, power_w, is_available,
       observed_at, previous_price_pln, price_change_pln,
       price_change_pct, pln_per_watt
FROM gold.product_price_history
ORDER BY observed_at, scrape_id;
"""

SQL_DAILY = """
SELECT observation_date, available_panels, avg_price_pln,
       avg_pln_per_watt, min_pln_per_watt, max_pln_per_watt
FROM gold.daily_market_prices
ORDER BY observation_date;
"""


def connection_config() -> dict:
    """Load locally configured DB credentials (never hardcode in repository)."""
    required = ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise ValueError(
            "Brak zmiennych bazy danych: " + ", ".join(missing) + ". "
            "Sprawdź plik .env w katalogu głównym repozytorium."
        )
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "dbname": os.environ["POSTGRES_DB"],
        "user": os.environ["POSTGRES_USER"],
        "password": os.environ["POSTGRES_PASSWORD"],
        "connect_timeout": 5,
        "options": "-c default_transaction_read_only=on",
    }


def _query_dataframe(conn: psycopg.Connection, query: str) -> pd.DataFrame:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query)
        rows = cur.fetchall()
        columns = [item.name for item in cur.description]
    return pd.DataFrame.from_records(rows, columns=columns)


def _numeric(df: pd.DataFrame, columns: tuple[str, ...]) -> None:
    for column in columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")


def load_gold_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read three Gold views in a single read-only transaction."""
    with psycopg.connect(**connection_config()) as conn:
        ranking = _query_dataframe(conn, SQL_RANKING)
        history = _query_dataframe(conn, SQL_HISTORY)
        daily = _query_dataframe(conn, SQL_DAILY)

    _numeric(ranking, ("overall_rank", "price_pln", "power_w", "pln_per_watt", "watt_per_pln"))
    _numeric(history, ("price_pln", "power_w", "previous_price_pln", "price_change_pln", "price_change_pct", "pln_per_watt"))
    _numeric(daily, ("available_panels", "avg_price_pln", "avg_pln_per_watt", "min_pln_per_watt", "max_pln_per_watt"))

    ranking["scraped_at"] = pd.to_datetime(ranking["scraped_at"])
    history["observed_at"] = pd.to_datetime(history["observed_at"])
    daily["observation_date"] = pd.to_datetime(daily["observation_date"])

    return ranking, history, daily

SQL_RUN_QUALITY = """
WITH recent AS (
    SELECT scrape_run_id, started_at, finished_at, status, products_count
    FROM bronze.scrape_runs
    ORDER BY started_at DESC, scrape_run_id DESC
    LIMIT 80
)
SELECT
    r.scrape_run_id::text AS scrape_run_id,
    r.started_at,
    r.finished_at,
    r.status,
    r.products_count AS expected_count,
    COUNT(p.scrape_id) AS actual_count,
    COUNT(p.scrape_id) FILTER (
        WHERE p.source_url IS NULL OR TRIM(p.source_url) = ''
    ) AS missing_urls,
    COUNT(p.scrape_id) FILTER (
        WHERE p.source_url IS NOT NULL AND TRIM(p.source_url) <> ''
    ) - COUNT(DISTINCT NULLIF(TRIM(p.source_url), '')) AS duplicate_urls
FROM recent r
LEFT JOIN bronze.panel_scrape_raw p ON p.scrape_run_id = r.scrape_run_id
GROUP BY r.scrape_run_id, r.started_at, r.finished_at, r.status, r.products_count
ORDER BY r.started_at DESC, r.scrape_run_id DESC;
"""


def load_run_quality() -> pd.DataFrame:
    """Read Bronze diagnostics, separately from mandatory Gold views.

    If Bronze read permission is missing, only the monitoring tab is affected.
    """
    with psycopg.connect(**connection_config()) as conn:
        runs = _query_dataframe(conn, SQL_RUN_QUALITY)
    for column in ("expected_count", "actual_count", "missing_urls", "duplicate_urls"):
        runs[column] = pd.to_numeric(runs[column], errors="coerce")
    runs["started_at"] = pd.to_datetime(runs["started_at"], errors="coerce")
    runs["finished_at"] = pd.to_datetime(runs["finished_at"], errors="coerce")
    return runs
