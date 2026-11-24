"""Local-only secrets bootstrap and coordinated PostgreSQL password rotation.

This script never prints secret values and does not manage Docker lifecycle.
Use on a trusted machine only; Docker daemon access is effectively privileged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import dotenv_values
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
ROOT_ENV = ROOT / ".env"
COMPOSE_ENV = ROOT / "docker" / ".env"
BACKUPS = ROOT / "backups"


class CredentialError(RuntimeError):
    pass


def password() -> str:
    return secrets.token_urlsafe(36)


def env_value(path: Path, name: str) -> str:
    return str(dotenv_values(path).get(name) or "")


def safe_properties(path: Path) -> None:
    if not path.is_file():
        raise CredentialError(f"Missing local config: {path}")
    if path.is_symlink():
        raise CredentialError(f"Refusing symlinked secrets file: {path}")


def atomic_secret_write(path: Path, contents: str) -> None:
    """Write in the target directory then atomically replace. Never print contents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise CredentialError(f"Refusing symlinked path: {path}")
    tmp = path.with_name(path.name + ".pending")
    if tmp.exists():
        raise CredentialError(f"Stale pending secrets file: {tmp}. Inspect it locally before retrying.")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(contents)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def compose_content(pg_pass: str, admin_pass: str) -> str:
    return (
        "# Local Docker Compose substitutions. Never commit.\n"
        f"POSTGRES_PASSWORD={pg_pass}\n"
        f"PGADMIN_DEFAULT_PASSWORD={admin_pass}\n"
    )


def update_root_password(existing: str, pg_pass: str) -> str:
    lines = existing.splitlines(keepends=True)
    occurrences = [i for i, line in enumerate(lines)
                   if re.match(r"^\s*POSTGRES_PASSWORD\s*=", line)]
    if len(occurrences) != 1:
        raise CredentialError("Root .env must contain exactly one POSTGRES_PASSWORD assignment")
    i = occurrences[0]
    ending = "\r\n" if lines[i].endswith("\r\n") else "\n"
    lines[i] = f"POSTGRES_PASSWORD={pg_pass}{ending}"
    return "".join(lines)


def db_connect(root_env: Path, *, override_password: str | None = None):
    vals = dotenv_values(root_env)
    host = str(vals.get("POSTGRES_HOST") or "localhost")
    if host not in ("localhost", "127.0.0.1", "::1"):
        raise CredentialError("Rotation permitted only against loopback PostgreSQL")
    user = str(vals.get("POSTGRES_USER") or "")
    if user != "postgres":
        raise CredentialError("For safety this tool only rotates the local postgres role")
    dbname = str(vals.get("POSTGRES_DB") or "")
    if dbname != "solar_prices":
        raise CredentialError("Unexpected database name (expected solar_prices)")
    pg_pass = override_password or str(vals.get("POSTGRES_PASSWORD") or "")
    if not pg_pass:
        raise CredentialError("Missing PostgreSQL password in root .env")
    return psycopg.connect(host=host, port=int(vals.get("POSTGRES_PORT") or 5432),
                           dbname=dbname, user=user, password=pg_pass,
                           connect_timeout=5, autocommit=True)


def check_verified_backup(directory: Path = BACKUPS, *, max_hours: int = 168) -> Path:
    """Require a recent, SHA-matching dump with successful isolated restore report."""
    candidates = sorted(directory.glob("solar_prices_*.dump"), key=lambda x: x.stat().st_mtime, reverse=True)
    now = datetime.now(timezone.utc)
    for dump in candidates:
        meta = dump.with_name(dump.name + ".json")
        report = dump.with_name(dump.name + ".verified.json")
        if not meta.is_file() or not report.is_file():
            continue
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
            r = json.loads(report.read_text(encoding="utf-8"))
            verified = datetime.fromisoformat(r["verified_utc"])
            if verified.tzinfo is None or not 0 <= (now - verified).total_seconds() <= max_hours * 3600:
                continue
            with dump.open("rb") as stream:
                hash_value = hashlib.file_digest(stream, "sha256").hexdigest()
            if m.get("format") == "pg_dump-custom" and m.get("sha256") == hash_value \
               and r.get("result") == "PASS" and r.get("sha256") == hash_value \
               and m.get("size_bytes") == dump.stat().st_size:
                return dump
        except (OSError, KeyError, ValueError, TypeError, json.JSONDecodeError):
            continue
    raise CredentialError("No recent verified PostgreSQL backup with matching SHA256; run backup create + verify first")


def change_role_password(conn, name: str, new_password: str) -> None:
    with conn.cursor() as cur:
        cur.execute(sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(
            sql.Identifier(name), sql.Literal(new_password)))


def initialize(root: Path = ROOT) -> None:
    root_file = root / ".env"
    compose_file = root / "docker" / ".env"
    if root_file.exists() or compose_file.exists():
        raise CredentialError("Existing credentials detected; init refuses to overwrite. Use rotate for a running project.")
    template = root / ".env.example"
    safe_properties(template)
    text = template.read_text(encoding="utf-8-sig")
    pg_pass = password()
    pgadmin_pass = password()
    new_root = update_root_password(text, pg_pass)
    atomic_secret_write(root_file, new_root)
    try:
        atomic_secret_write(compose_file, compose_content(pg_pass, pgadmin_pass))
    except Exception:
        root_file.unlink(missing_ok=True)
        raise
    print("Created root .env and docker/.env with unique random local credentials. No services changed.")


def rotate(root: Path = ROOT, *, require_backup: bool = True) -> None:
    """Change existing PG role password + both local files; attempt rollback on failure."""
    root_file = root / ".env"
    compose_file = root / "docker" / ".env"
    safe_properties(root_file)
    backup = check_verified_backup(root / "backups") if require_backup else None
    previous = root_file.read_text(encoding="utf-8-sig")
    previous_compose = compose_file.read_text(encoding="utf-8") if compose_file.exists() else None
    current = env_value(root_file, "POSTGRES_PASSWORD")
    if not current:
        raise CredentialError("Missing current PostgreSQL credential")
    if previous_compose is not None and env_value(compose_file, "POSTGRES_PASSWORD") != current:
        raise CredentialError("root .env and docker/.env disagree; refusing rotation")

    pg_pass, admin_pass = password(), password()
    future_root = update_root_password(previous, pg_pass)
    future_compose = compose_content(pg_pass, admin_pass)

    # Authenticate *before* any mutation.
    with db_connect(root_file) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_user")
            if cur.fetchone()[0] != "postgres":
                raise CredentialError("Connected with unexpected role")
        changed = False
        try:
            change_role_password(conn, "postgres", pg_pass)
            changed = True
            # Confirm a fresh authenticated connection before swapping app files.
            with db_connect(root_file, override_password=pg_pass) as verify:
                with verify.cursor() as cur:
                    cur.execute("SELECT 1")
                    assert cur.fetchone()[0] == 1
            atomic_secret_write(root_file, future_root)
            atomic_secret_write(compose_file, future_compose)
        except Exception as exc:
            # Keep old open connection available for a best-effort SQL rollback.
            errors = []
            if changed:
                try:
                    change_role_password(conn, "postgres", current)
                except Exception:
                    errors.append("database rollback failed")
            try:
                if root_file.read_text(encoding="utf-8-sig") != previous:
                    atomic_secret_write(root_file, previous)
                if previous_compose is None:
                    compose_file.unlink(missing_ok=True)
                elif compose_file.read_text(encoding="utf-8") != previous_compose:
                    atomic_secret_write(compose_file, previous_compose)
            except Exception:
                errors.append("local file rollback failed")
            raise CredentialError("Rotation stopped; " + (", ".join(errors) if errors else "rollback attempted") +
                                  ". Check connectivity before running Docker Compose.") from exc
    print("PostgreSQL role password updated, verified and synchronized to root .env / docker/.env.")
    if backup:
        print(f"Verified backup prerequisite: {backup.name}")
    print("Next: recreate postgres, airflow and pgadmin (never use down -v). Dashboard reader secret is unchanged.")


def check(root: Path = ROOT) -> None:
    root_file, compose_file = root / ".env", root / "docker" / ".env"
    safe_properties(root_file)
    safe_properties(compose_file)
    if env_value(root_file, "POSTGRES_PASSWORD") != env_value(compose_file, "POSTGRES_PASSWORD"):
        raise CredentialError("Root and Compose PostgreSQL passwords differ")
    for key in ("POSTGRES_PASSWORD", "PGADMIN_DEFAULT_PASSWORD"):
        if os.getenv(key) and os.environ[key] != env_value(compose_file, key):
            raise CredentialError(f"Shell variable {key} overrides docker/.env with a different value")
    if env_value(compose_file, "PGADMIN_DEFAULT_PASSWORD") in ("", "admin"):
        raise CredentialError("Missing or default pgAdmin password")
    with db_connect(root_file) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM bronze.scrape_runs")
            count = cur.fetchone()[0]
    print(f"Credential check PASS: PostgreSQL login works; {count} scrape runs in Bronze.")


def main() -> None:
    parser = argparse.ArgumentParser(description="E2E Solar local credential init/rotation. No secrets printed.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Generate credentials for a FRESH clone only (before first DB initialization)")
    rotate_parser = sub.add_parser("rotate", help="Rotate running local database + pgAdmin credentials")
    rotate_parser.add_argument("--confirm", choices=["ROTATE_LOCAL_CREDENTIALS"], required=True,
                               help="Explicit acknowledgement; requires a recent verified backup")
    sub.add_parser("check", help="Verify synchronized local secrets and PostgreSQL login")
    args = parser.parse_args()
    try:
        if args.command == "init":
            initialize()
        elif args.command == "rotate":
            rotate()
        else:
            check()
    except (CredentialError, OSError, psycopg.Error) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
