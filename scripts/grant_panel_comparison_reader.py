"""Grant/check SELECT access to the new PV comparison Gold view.

Usage from repo root after `dbt build`:
    uv run --frozen python scripts/grant_panel_comparison_reader.py
    uv run --frozen python scripts/grant_panel_comparison_reader.py --check

Does not touch data, role passwords, or previous views. --check is read-only.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READER_ROLE = "solar_dashboard"


def credentials():
    from dotenv import dotenv_values

    admin_path = ROOT / ".env"
    reader_path = ROOT / "dashboard" / ".env"
    if not admin_path.is_file() or not reader_path.is_file():
        raise RuntimeError("Missing root .env or dashboard/.env")
    admin = dotenv_values(admin_path)
    reader = dotenv_values(reader_path)
    required = ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
    if any(not admin.get(k) for k in required) or any(not reader.get(k) for k in required):
        raise RuntimeError("Incomplete local credentials")
    if reader["POSTGRES_USER"] != READER_ROLE:
        raise RuntimeError("dashboard/.env must use the dedicated solar_dashboard role")
    common = {
        "host": admin.get("POSTGRES_HOST") or "localhost",
        "port": int(admin.get("POSTGRES_PORT") or "5432"),
        "dbname": admin["POSTGRES_DB"],
        "connect_timeout": 7,
    }
    return (
        {**common, "user": admin["POSTGRES_USER"], "password": admin["POSTGRES_PASSWORD"]},
        {**common, "user": READER_ROLE, "password": reader["POSTGRES_PASSWORD"],
         "options": "-c default_transaction_read_only=on"},
    )


def grant(admin) -> None:
    import psycopg

    with psycopg.connect(**admin) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'gold'
                      AND c.relname = 'panel_technical_comparison'
                      AND c.relkind IN ('v', 'm')
                )
            """)
            if not cur.fetchone()[0]:
                raise RuntimeError("Missing gold.panel_technical_comparison: run dbt build first")
            cur.execute("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = 'solar_dashboard')")
            if not cur.fetchone()[0]:
                raise RuntimeError("Missing solar_dashboard role")
            cur.execute("GRANT USAGE ON SCHEMA gold TO solar_dashboard")
            cur.execute("GRANT SELECT ON gold.panel_technical_comparison TO solar_dashboard")
    print("GRANT PASS: solar_dashboard can SELECT the technical comparison view")


def check(reader) -> int:
    import psycopg

    with psycopg.connect(**reader) as conn:
        with conn.cursor() as cur:
            cur.execute("SHOW transaction_read_only")
            if cur.fetchone()[0] != "on":
                raise RuntimeError("Reader session is not read-only")
            cur.execute("SELECT COUNT(*) FROM gold.panel_technical_comparison")
            count = cur.fetchone()[0]
    print(f"READER PASS: read-only solar_dashboard accesses {count} current comparisons")
    return count


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Authorize dashboard technical view read-only access")
    parser.add_argument("--check", action="store_true", help="Verify without changing grants")
    args = parser.parse_args(argv)
    try:
        admin, reader = credentials()
        if not args.check:
            grant(admin)
        check(reader)
        return 0
    except Exception as exc:
        # In particular, avoid echoing DSNs or passwords in database exceptions.
        print(f"READER FAIL: {type(exc).__name__} (check view and local credentials)")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
