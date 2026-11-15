"""Repair existing dashboard SELECT grants and future dbt Gold view grants.

From repository root (Windows PowerShell):
    uv run --frozen python scripts/repair_dashboard_permissions.py

Only grants read privileges. Does not reset tables, alter secrets or roles,
or execute any scraping or dbt jobs.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ADMIN_ENV = ROOT / ".env"
READER_ENV = ROOT / "dashboard" / ".env"
READER_ROLE = "solar_dashboard"
GOLD_VIEWS = ("current_panel_ranking", "product_price_history", "daily_market_prices")
BRONZE_TABLES = ("scrape_runs", "panel_scrape_raw")


def load_local_credentials(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError(f"Brak pliku {path}. Nie tworzę ani nie nadpisuję haseł.")
    env = dotenv_values(path)
    required = ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise RuntimeError(f"Niekompletna konfiguracja w {path}: {', '.join(missing)}")
    return {
        "host": env.get("POSTGRES_HOST") or "localhost",
        "port": int(env.get("POSTGRES_PORT") or "5432"),
        "dbname": env["POSTGRES_DB"],
        "user": env["POSTGRES_USER"],
        "password": env["POSTGRES_PASSWORD"],
        "connect_timeout": 7,
    }


def validate_gold_owners(owners: dict[str, str]) -> None:
    missing = sorted(set(GOLD_VIEWS) - set(owners))
    if missing:
        raise RuntimeError(
            "Brak widoków Gold: " + ", ".join(missing) + ". "
            "Najpierw zweryfikuj dbt build; nie tworzę fikcyjnych widoków."
        )


def grant_reader_access(admin: dict) -> None:
    import psycopg
    from psycopg import sql

    with psycopg.connect(**admin) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (READER_ROLE,))
            if cur.fetchone() is None:
                raise RuntimeError(
                    "Brak roli solar_dashboard. Nie tworzę nowego konta; "
                    "sprawdź dashboard/.env i bootstrap czytelnika."
                )
            cur.execute("""
                SELECT c.relname, pg_get_userbyid(c.relowner)
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'gold'
                  AND c.relkind IN ('v', 'm')
                  AND c.relname = ANY(%s)
            """, (list(GOLD_VIEWS),))
            owners = dict(cur.fetchall())
            validate_gold_owners(owners)
            # The DBT login comes from root .env. Also protect relations owned
            # by currently observed model owner(s), in case those differ.
            role_creators = set(owners.values()) | {str(admin["user"])}

            cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(str(admin["dbname"])), sql.Identifier(READER_ROLE)))
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA gold, bronze TO {}").format(
                sql.Identifier(READER_ROLE)))
            for name in GOLD_VIEWS:
                cur.execute(sql.SQL("GRANT SELECT ON TABLE {}.{} TO {}").format(
                    sql.Identifier("gold"), sql.Identifier(name), sql.Identifier(READER_ROLE)))
            for name in BRONZE_TABLES:
                cur.execute(sql.SQL("GRANT SELECT ON TABLE {}.{} TO {}").format(
                    sql.Identifier("bronze"), sql.Identifier(name), sql.Identifier(READER_ROLE)))
            # Default privileges are specific to the creating role + schema.
            # `ON TABLES` includes views. Replaced dbt views inherit SELECT.
            for creator in sorted(role_creators):
                cur.execute(sql.SQL(
                    "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA gold "
                    "GRANT SELECT ON TABLES TO {}"
                ).format(sql.Identifier(creator), sql.Identifier(READER_ROLE)))
    print("GRANT PASS — obecne 3 widoki Gold i 2 tabele Bronze udostępnione solar_dashboard.")
    print("DEFAULT PRIVILEGES PASS — nowe widoki Gold utworzone przez dbt zachowają SELECT.")


def check_reader_access(admin: dict, reader: dict) -> None:
    import psycopg
    from psycopg import sql

    config = dict(admin)
    config["user"] = reader["user"]
    config["password"] = reader["password"]
    config["options"] = "-c default_transaction_read_only=on"
    with psycopg.connect(**config) as conn:
        with conn.cursor() as cur:
            for name in GOLD_VIEWS:
                cur.execute(sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                    sql.Identifier("gold"), sql.Identifier(name)))
                cur.fetchone()
            for name in BRONZE_TABLES:
                cur.execute(sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                    sql.Identifier("bronze"), sql.Identifier(name)))
                cur.fetchone()
            cur.execute("SHOW transaction_read_only")
            assert cur.fetchone()[0] == "on", "Sesja dashboardu musi być read-only"
    print("READER PASS — nowe połączenie solar_dashboard czyta Gold/Bronze (read-only).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair or verify Streamlit DB reader grants")
    parser.add_argument("--check", action="store_true", help="Verify only; do not change PostgreSQL grants")
    args = parser.parse_args()
    admin = load_local_credentials(ADMIN_ENV)
    reader = load_local_credentials(READER_ENV)
    if reader["user"] != READER_ROLE:
        raise RuntimeError("dashboard/.env nie jest kontem solar_dashboard. Zatrzymano.")
    if not args.check:
        grant_reader_access(admin)
    check_reader_access(admin, reader)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Avoid printing DB connection details/passwords in verbose errors.
        raise SystemExit(f"NAPRAWA NIEUDANA: {type(exc).__name__}. Szczegóły: {str(exc).split('password=')[0][:300]}") from None
