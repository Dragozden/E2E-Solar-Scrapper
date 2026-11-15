"""Real PostgreSQL fixture/assertions for CI technical-spec dbt models.

Never use against a development or production database. Requires the same
GitHub Actions-only environment guard as scripts/ci_dbt_integration.py.

CI: after ci_dbt_integration.py seed, run `seed`; after dbt build, run `assert`.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci_dbt_integration import PREFIX, connection


def _sample(power: int, voc: float, vmp: float, isc: float, imp: float) -> dict:
    return {
        "rated_power_w": power, "voc_v": voc, "vmp_v": vmp,
        "isc_a": isc, "imp_a": imp,
        "manufacturer": "CI fixture", "model": "SYNTHETIC-ONLY",
    }


def seed() -> None:
    """CI fixture: two versions of A, incomplete B, historical-only C, no D."""
    samples = [
        (PREFIX + "a", datetime(2026, 10, 1, tzinfo=timezone.utc),
         "Old panel A", _sample(500, 45, 37, 14.5, 13.51), [], "a" * 64),
        (PREFIX + "a", datetime(2026, 10, 2, tzinfo=timezone.utc),
         "Newest panel A", _sample(500, 46, 37, 14.5, 13.51), [], "b" * 64),
        (PREFIX + "b", datetime(2026, 10, 2, tzinfo=timezone.utc),
         "Incomplete panel B", {"efficiency_pct": 22.3, "max_system_voltage_v": "999999999999999999999999999"},
         ["range_not_exact_efficiency_pct"], "c" * 64),
        (PREFIX + "c", datetime(2026, 10, 1, tzinfo=timezone.utc),
         "Historical panel C", _sample(600, 50, 43, 15, 13.95), [], "d" * 64),
    ]
    with connection() as conn:
        with conn.cursor() as cur:
            for url, fetched, title, values, issues, digest in samples:
                cur.execute("""
                    INSERT INTO bronze.panel_spec_snapshots (
                        source_url, fetched_at, page_title, attributes_raw,
                        normalized_values, datasheet_urls, parse_issues,
                        spec_hash, parser_version
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (url, fetched, title, Jsonb([]), Jsonb(values),
                      Jsonb([]), Jsonb(issues), digest, "ci-fixture-v1"))
    print("CI spec seed OK: four versions, including duplicate product URL A")


def assert_models() -> None:
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM silver.stg_panel_specs")
            assert cur.fetchone()[0] == 4
            cur.execute("SELECT COUNT(*), COUNT(DISTINCT source_url) FROM gold.panel_technical_comparison")
            assert cur.fetchone() == (3, 3), "Enrichment must preserve current ranking grain"
            cur.execute("""
                SELECT technical_status, is_technical_comparable, spec_fetched_at,
                       voc_v, technical_power_w
                FROM gold.panel_technical_comparison WHERE source_url = %s
            """, (PREFIX + "a",))
            a = cur.fetchone()
            assert a[0] == "PASS" and a[1] is True, a
            assert a[2].date().isoformat() == "2026-10-02", a
            assert a[3] == Decimal("46.0000") and a[4] == Decimal("500.0000"), a
            cur.execute("""
                SELECT technical_status, is_technical_comparable
                FROM gold.panel_technical_comparison WHERE source_url = %s
            """, (PREFIX + "b",))
            assert cur.fetchone() == ("INCOMPLETE", False)
            cur.execute("""SELECT max_system_voltage_v FROM silver.stg_panel_specs
                           WHERE source_url = %s""", (PREFIX + "b",))
            assert cur.fetchone() == (None,), "Oversized JSON value must normalize to NULL"
            cur.execute("""
                SELECT technical_status, is_technical_comparable, spec_id
                FROM gold.panel_technical_comparison WHERE source_url = %s
            """, (PREFIX + "d",))
            assert cur.fetchone() == ("NOT_ENRICHED", False, None)
            cur.execute("SELECT COUNT(*) FROM gold.panel_technical_comparison WHERE source_url = %s",
                        (PREFIX + "c",))
            assert cur.fetchone()[0] == 0, "Historical offer must not enter latest ranking"
    print("CI spec assertions OK: latest version, incomplete, not-enriched, no duplicate URLs")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("seed", "assert"):
        raise SystemExit("Usage: python scripts/ci_panel_specs.py [seed|assert]")
    if sys.argv[1] == "seed":
        seed()
    else:
        assert_models()
