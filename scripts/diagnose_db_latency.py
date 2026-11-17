"""Read-only step timing for the local E2E Solar batch CLI.

From the repository root:
    uv run --frozen python -u scripts/diagnose_db_latency.py
    uv run --frozen python -u scripts/diagnose_db_latency.py --ipv4

Neither mode changes PostgreSQL, Docker, .env files or the scraper. The --ipv4
mode is restricted to deployments whose configured host is localhost/127.0.0.1.
The configured DB credentials are never printed. No network contact with shops.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Deliberately read-only; query reproduces the costly parts of plan/status.
QUERIES = (
    ("ping (SELECT 1)", "SELECT 1"),
    ("catalog (Gold)", "SELECT COUNT(*) FROM gold.current_panel_ranking"),
    ("technical status (Gold)", """
        SELECT technical_status, COUNT(*)
        FROM gold.panel_technical_comparison
        GROUP BY technical_status
    """),
    ("attempt history (Bronze)", """
        SELECT outcome, COUNT(*) FROM bronze.panel_spec_attempts GROUP BY outcome
    """),
    ("plan joins (Gold + Bronze)", """
        SELECT r.source_url, r.title, r.overall_rank, r.power_w,
               s.spec_id, s.normalized_values, s.parse_issues, s.fetched_at,
               a.attempted_at, a.outcome
        FROM gold.current_panel_ranking r
        LEFT JOIN LATERAL (
            SELECT spec_id, normalized_values, parse_issues, fetched_at
            FROM bronze.panel_spec_snapshots
            WHERE source_url = r.source_url
            ORDER BY fetched_at DESC, spec_id DESC
            LIMIT 1
        ) s ON TRUE
        LEFT JOIN LATERAL (
            SELECT attempted_at, outcome
            FROM bronze.panel_spec_attempts
            WHERE source_url = r.source_url
            ORDER BY attempted_at DESC, attempt_id DESC
            LIMIT 1
        ) a ON TRUE
        WHERE r.is_available IS TRUE AND r.source_url IS NOT NULL
        ORDER BY r.overall_rank, r.source_url
    """),
)


def ipv4_host(configured: str | None) -> str:
    """Only permit switching local loopback: never redirect a remote DB."""
    if (configured or "").lower() not in ("localhost", "127.0.0.1"):
        raise ValueError("--ipv4 applies only when POSTGRES_HOST is localhost/127.0.0.1")
    return "127.0.0.1"


def timed(label: str, fn, *, emit=print):
    start = perf_counter()
    try:
        result = fn()
    except Exception as exc:
        emit(f"FAIL {label}: {perf_counter() - start:.3f}s ({type(exc).__name__})")
        raise
    emit(f"TIME {label}: {perf_counter() - start:.3f}s")
    return result


def timed_query(conn, label: str, sql: str, *, emit=print) -> int:
    def run() -> int:
        with conn.cursor() as cur:
            cur.execute(sql)
            return len(cur.fetchall())
    count = timed(label, run, emit=emit)
    emit(f"  rows={count}")
    return count


def probe(*, ipv4: bool = False, emit=print) -> bool:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    if ipv4:
        os.environ["POSTGRES_HOST"] = ipv4_host(os.getenv("POSTGRES_HOST"))
    from scraper.config import config
    from scraper.load import get_connection

    emit(f"DB timing: host={config.host} port={config.port}; no writes; "
         "limits: connection 10s / SQL 15s / lock 3s")
    start = perf_counter()
    try:
        conn = timed("PostgreSQL connect", get_connection, emit=emit)
        with conn:
            with conn.cursor() as cur:
                # Read-only transaction. Limits are local to this connection.
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("SET LOCAL statement_timeout = '15s'")
                cur.execute("SET LOCAL lock_timeout = '3s'")
            for name, query in QUERIES:
                timed_query(conn, name, query, emit=emit)
    except Exception as exc:
        emit(f"DIAG FAIL ({type(exc).__name__}), elapsed={perf_counter() - start:.3f}s")
        return False
    emit(f"DIAG PASS, total={perf_counter() - start:.3f}s")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only timings of E2E Solar PostgreSQL operations")
    parser.add_argument("--ipv4", action="store_true", help="Try local 127.0.0.1 without editing .env")
    args = parser.parse_args(argv)
    try:
        return 0 if probe(ipv4=args.ipv4) else 1
    except (ValueError, OSError) as exc:
        print(f"DIAG ERROR: {type(exc).__name__} (no configuration was changed)", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
