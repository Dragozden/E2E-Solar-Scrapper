"""CI-only setup and assertions for dbt on ephemeral PostgreSQL.

Usage:
    python scripts/ci_dbt_integration.py seed
    dbt build ...
    python scripts/ci_dbt_integration.py assert

Never point this utility at a persistent/user database. It deliberately
creates schema, seeds observations and validates expected analytics.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg

ROOT = Path(__file__).resolve().parents[1]
FIRST = UUID("11111111-1111-4111-8111-111111111111")
SECOND = UUID("22222222-2222-4222-8222-222222222222")
PREFIX = "https://example.test/ci-solar/"


def connection():
    required = ["POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Missing DB environment variables: {missing}")
    if (os.getenv("CI") != "true" or os.getenv("GITHUB_ACTIONS") != "true"
            or os.getenv("POSTGRES_DB") != "solar_prices"):
        raise RuntimeError("CI database fixture may run only under GitHub Actions against solar_prices")
    return psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=10,
    )


def initialize_schema(cur):
    files = sorted((ROOT / "docker" / "postgres" / "init").glob("[0-9]*.sql"))
    if len(files) < 5:
        raise AssertionError(f"Expected repository's five Bronze initialization SQL scripts, got {len(files)}")
    for path in files:
        # The source SQL includes UTF-8 BOM in some files.
        script = path.read_text(encoding="utf-8-sig")
        for statement in script.split(";"):
            if statement.strip():
                cur.execute(statement)


def seed():
    with connection() as conn:
        with conn.cursor() as cur:
            initialize_schema(cur)
            cur.executemany(
                """
                INSERT INTO bronze.scrape_runs
                    (scrape_run_id, started_at, finished_at, status, products_count)
                VALUES (%s, %s, %s, 'SUCCESS', %s)
                """,
                [
                    (FIRST, datetime(2026, 10, 1, 7, 0), datetime(2026, 10, 1, 7, 5), 3),
                    (SECOND, datetime(2026, 10, 2, 7, 0), datetime(2026, 10, 2, 7, 5), 3),
                ],
            )
            cur.executemany(
                """
                INSERT INTO bronze.panel_scrape_raw
                    (scrape_run_id, title, price_text, power_text, source_url, is_available)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [
                    (FIRST, "Panel A 500 W", "400.00", "500 W", PREFIX + "a", True),
                    (FIRST, "Panel B 450 W", "350.00", "450 W", PREFIX + "b", True),
                    (FIRST, "Panel C 600 W", "500.00", "600 W", PREFIX + "c", False),
                    (SECOND, "Panel A 500 W", "375.00", "500 W", PREFIX + "a", True),
                    (SECOND, "Panel B 450 W", "350.00", "450 W", PREFIX + "b", True),
                    (SECOND, "Panel D 550 W", "450.00", "550 W", PREFIX + "d", True),
                ],
            )
    print("CI Bronze seed OK: 2 successful scrape runs, 6 panel observations")


def assert_models():
    with connection() as conn:
        with conn.cursor() as cur:
            for table, expected in [
                ("silver.stg_panels", 6),
                ("gold.current_panel_ranking", 3),
                ("gold.product_price_history", 6),
                ("gold.daily_market_prices", 2),
            ]:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                actual = cur.fetchone()[0]
                assert actual == expected, f"{table}: expected {expected} rows, got {actual}"

            cur.execute(
                """SELECT price_pln, previous_price_pln, price_change_pln,
                          price_change_pct
                   FROM gold.product_price_history
                   WHERE source_url = %s
                   ORDER BY observed_at DESC LIMIT 1""",
                (PREFIX + "a",),
            )
            latest_price = cur.fetchone()
            expected_price = (Decimal("375.00"), Decimal("400.00"),
                              Decimal("-25.00"), Decimal("-6.25"))
            assert latest_price == expected_price, (latest_price, expected_price)

            cur.execute(
                """SELECT observation_date, available_panels
                   FROM gold.daily_market_prices
                   ORDER BY observation_date"""
            )
            daily = cur.fetchall()
            assert [row[1] for row in daily] == [2, 3], daily

            cur.execute(
                """SELECT source_url, pln_per_watt
                   FROM gold.current_panel_ranking ORDER BY overall_rank LIMIT 1"""
            )
            top = cur.fetchone()
            assert top == (PREFIX + "a", Decimal("0.7500")), top

    print("CI Silver/Gold assertions OK: grains, price change, availability, ranking")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("seed", "assert"):
        raise SystemExit("Usage: python scripts/ci_dbt_integration.py [seed|assert]")
    if sys.argv[1] == "seed":
        seed()
    else:
        assert_models()
