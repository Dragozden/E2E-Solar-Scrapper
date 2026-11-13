"""One-time local bootstrap: dedicated SELECT-only PostgreSQL login for Streamlit.

Usage from repository root: uv run python scripts/setup_dashboard_reader.py
Requires existing root .env and a running PostgreSQL container with Gold views.
Does not reset/recreate databases, volumes, or historical rows.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
ADMIN_ENV = ROOT / ".env"
READER_ENV = ROOT / "dashboard" / ".env"
READER_ROLE = "solar_dashboard"
GOLD_VIEWS = ("current_panel_ranking", "product_price_history", "daily_market_prices")
BRONZE_TABLES = ("scrape_runs", "panel_scrape_raw")


def load_admin_config() -> dict[str, object]:
    if not ADMIN_ENV.is_file():
        raise RuntimeError(f"Brak {ADMIN_ENV}. Skonfiguruj istniejący .env projektu.")
    env = dotenv_values(ADMIN_ENV)
    required = ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
    missing = [key for key in required if not env.get(key)]
    if missing:
        raise RuntimeError("Brak zmiennych w głównym .env: " + ", ".join(missing))
    return dict(
        host=env.get("POSTGRES_HOST") or "localhost",
        port=int(env.get("POSTGRES_PORT") or "5432"),
        dbname=env["POSTGRES_DB"],
        user=env["POSTGRES_USER"],
        password=env["POSTGRES_PASSWORD"],
        connect_timeout=7,
    )


def reader_env_content(database: str, password: str) -> str:
    # token_urlsafe() yields characters safe for unquoted python-dotenv values.
    return (
        "# Streamlit container only. Generated locally; DO NOT COMMIT.\n"
        "POSTGRES_HOST=postgres\n"
        "POSTGRES_PORT=5432\n"
        f"POSTGRES_DB={database}\n"
        f"POSTGRES_USER={READER_ROLE}\n"
        f"POSTGRES_PASSWORD={password}\n"
    )


def verify_reader(reader_env: Path, admin: dict[str, object]) -> None:
    env = dotenv_values(reader_env)
    config = dict(
        host=admin["host"],
        port=admin["port"],
        dbname=admin["dbname"],
        user=env["POSTGRES_USER"],
        password=env["POSTGRES_PASSWORD"],
        connect_timeout=7,
        options="-c default_transaction_read_only=on",
    )
    with psycopg.connect(**config) as conn:
        with conn.cursor() as cur:
            for view in GOLD_VIEWS:
                cur.execute(sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                    sql.Identifier("gold"), sql.Identifier(view)
                ))
                cur.fetchone()
            for table in BRONZE_TABLES:
                cur.execute(sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                    sql.Identifier("bronze"), sql.Identifier(table)
                ))
                cur.fetchone()
            cur.execute("SHOW transaction_read_only")
            if cur.fetchone()[0] != "on":
                raise RuntimeError("Nie działa tryb read-only sesji PostgreSQL.")
    print("OK: solar_dashboard może odczytać 3 modele Gold i 2 tabele Bronze (read-only).")


def provision_reader(admin: dict[str, object], password: str) -> None:
    with psycopg.connect(**admin) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (READER_ROLE,))
            if cur.fetchone():
                raise RuntimeError(
                    f"Rola {READER_ROLE} już istnieje, ale {READER_ENV} nie ma na dysku. "
                    "Nie nadpisuję istniejących uprawnień. Sprawdź konto ręcznie."
                )
            cur.execute(sql.SQL(
                "CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "NOREPLICATION NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(READER_ROLE), sql.Literal(password)))
            cur.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(
                sql.Identifier(READER_ROLE)
            ))
            cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(str(admin["dbname"])), sql.Identifier(READER_ROLE)
            ))
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA bronze, gold TO {}").format(
                sql.Identifier(READER_ROLE)
            ))
            for view in GOLD_VIEWS:
                cur.execute(sql.SQL("GRANT SELECT ON TABLE {}.{} TO {}").format(
                    sql.Identifier("gold"), sql.Identifier(view), sql.Identifier(READER_ROLE)
                ))
            for table in BRONZE_TABLES:
                cur.execute(sql.SQL("GRANT SELECT ON TABLE {}.{} TO {}").format(
                    sql.Identifier("bronze"), sql.Identifier(table), sql.Identifier(READER_ROLE)
                ))


def main() -> None:
    admin = load_admin_config()
    if READER_ENV.exists():
        print(f"Istnieje {READER_ENV}; nie zmieniam hasła ani uprawnień.")
        verify_reader(READER_ENV, admin)
        return

    password = secrets.token_urlsafe(36)
    provision_reader(admin, password)
    # The file is not tracked (.gitignore already ignores every .env filename).
    # Create exclusively; never silently overwrite an existing file with credentials.
    READER_ENV.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(READER_ENV, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(reader_env_content(str(admin["dbname"]), password))
    print(f"Wygenerowano {READER_ENV} (losowe hasło; nie dodawaj do Git).")
    verify_reader(READER_ENV, admin)


if __name__ == "__main__":
    main()
