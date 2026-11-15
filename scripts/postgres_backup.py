"""Safe local PostgreSQL backups and isolated verification for E2E Solar.

Commands (from repository root):
    uv run python scripts/postgres_backup.py create
    uv run python scripts/postgres_backup.py verify
    uv run python scripts/postgres_backup.py verify backups/solar_prices_....dump

No changes are made to the production database during verification.
Requires Docker Desktop and a running `solar-postgres` container for `create`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_DIR = ROOT / "backups"
DEFAULT_CONTAINER = "solar-postgres"
POSTGRES_IMAGE = "postgres:17"
RESTORE_DB = "solar_restore"


class BackupError(RuntimeError):
    """Raised for failed backup, validation, or Docker operations."""


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Execute docker as an argv list; never interpolate input into a shell."""
    if shutil.which("docker") is None:
        raise BackupError("Docker CLI nie jest dostepny w PATH.")
    result = subprocess.run(
        ["docker", *args], text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if check and result.returncode:
        details = (result.stderr or result.stdout).strip()
        raise BackupError(f"Docker command failed (exit {result.returncode}): {details[:2500]}")
    return result


def safe_db_name(name: str) -> str:
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name):
        raise BackupError(f"Unexpected PostgreSQL database/user name: {name!r}")
    return name


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def manifest_path(dump: Path) -> Path:
    return dump.with_name(dump.name + ".json")


def validate_manifest(dump: Path) -> dict:
    if not dump.is_file():
        raise BackupError(f"Nie znaleziono backupu: {dump}")
    meta_file = manifest_path(dump)
    if not meta_file.is_file():
        raise BackupError(f"Brak metadanych SHA256: {meta_file}")
    metadata = json.loads(meta_file.read_text(encoding="utf-8"))
    if metadata.get("format") != "pg_dump-custom" or metadata.get("sha256") != sha256_file(dump):
        raise BackupError("Checksum SHA256 nie zgadza sie z manifestem lub format jest zly.")
    if metadata.get("size_bytes") != dump.stat().st_size or dump.stat().st_size <= 0:
        raise BackupError("Niezgodny lub pusty plik backupu.")
    return metadata


def latest_backup(directory: Path) -> Path:
    backups = sorted(directory.glob("solar_prices_*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        raise BackupError(f"Brak plikow .dump w katalogu {directory}")
    return backups[0]


def create_backup(directory: Path, container: str = DEFAULT_CONTAINER) -> Path:
    """Custom-format logical dump, transferred as bytes via docker cp (PS-safe)."""
    if docker("inspect", "-f", "{{.State.Running}}", container).stdout.strip() != "true":
        raise BackupError(f"Kontener {container} nie dziala.")
    db_user = safe_db_name(docker("exec", container, "printenv", "POSTGRES_USER").stdout.strip())
    db_name = safe_db_name(docker("exec", container, "printenv", "POSTGRES_DB").stdout.strip())
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir():
        raise BackupError("Nie mozna utworzyc katalogu backupow.")
    filename = f"solar_prices_{datetime.now(timezone.utc):%Y%m%d_%H%M%SZ}_{uuid4().hex[:8]}.dump"
    target = directory / filename
    partial = directory / (filename + ".partial")
    temp_inside = f"/tmp/e2e-solar-{uuid4().hex}.dump"

    try:
        print(f"Tworze kopie bazy {db_name} z kontenera {container} (bez zatrzymywania ETL)...")
        docker("exec", container, "pg_dump", "--username", db_user,
               "--dbname", db_name, "--format=custom", "--compress=6",
               "--no-owner", "--no-acl", f"--file={temp_inside}")
        docker("exec", container, "pg_restore", "--list", temp_inside)
        docker("cp", f"{container}:{temp_inside}", str(partial))
        if not partial.is_file() or partial.stat().st_size == 0:
            raise BackupError("Plik backupu jest pusty lub nie zostal skopiowany.")
        hash_value = sha256_file(partial)
        partial.replace(target)
        metadata = {
            "format": "pg_dump-custom", "created_utc": datetime.now(timezone.utc).isoformat(),
            "database": db_name, "container": container, "size_bytes": target.stat().st_size,
            "sha256": hash_value, "pg_image_for_verification": POSTGRES_IMAGE,
        }
        meta_temp = manifest_path(target).with_suffix(".json.partial")
        meta_temp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        meta_temp.replace(manifest_path(target))
        print(f"Backup: {target}\nSHA256: {hash_value}\nRozmiar: {target.stat().st_size:,} B")
        return target
    finally:
        docker("exec", container, "rm", "-f", temp_inside, check=False)
        partial.unlink(missing_ok=True)


def restore_run_args(name: str, volume: str, password: str) -> list[str]:
    """Isolated PostgreSQL: no published port, no attachment to production network."""
    return [
        "run", "-d", "--name", name, "--network", "none",
        "-e", "POSTGRES_USER=postgres", "-e", f"POSTGRES_PASSWORD={password}",
        "-e", f"POSTGRES_DB={RESTORE_DB}",
        "-v", f"{volume}:/var/lib/postgresql/data", POSTGRES_IMAGE,
    ]


def restore_query_args(name: str) -> list[str]:
    counts_sql = """
    SELECT json_build_object(
        'scrape_runs', (SELECT COUNT(*) FROM bronze.scrape_runs),
        'raw_panels', (SELECT COUNT(*) FROM bronze.panel_scrape_raw),
        'silver_panels', (SELECT COUNT(*) FROM silver.stg_panels),
        'gold_ranking', (SELECT COUNT(*) FROM gold.current_panel_ranking),
        'gold_history', (SELECT COUNT(*) FROM gold.product_price_history),
        'gold_daily', (SELECT COUNT(*) FROM gold.daily_market_prices)
    )::text;
    """
    return ["exec", name, "psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
            "--username=postgres", f"--dbname={RESTORE_DB}", "-c", counts_sql]


def verify_backup(dump: Path, *, wait_seconds: int = 90) -> dict:
    """Restore dump to a newly generated, isolated PostgreSQL 17 volume.

    Never issues SQL or restore commands against solar-postgres.
    The disposable container and volume are removed in finally.
    """
    metadata = validate_manifest(dump)
    nonce = uuid4().hex[:12]
    name = f"solar-restore-verify-{nonce}"
    volume = f"solar-restore-verify-data-{nonce}"
    password = secrets.token_urlsafe(30)
    created_volume = False
    try:
        docker("volume", "create", volume)
        created_volume = True
        docker(*restore_run_args(name, volume, password))
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            ready = docker("exec", name, "pg_isready", "-U", "postgres", "-d", RESTORE_DB, check=False)
            if ready.returncode == 0:
                break
            time.sleep(2)
        else:
            raise BackupError("Tymczasowy PostgreSQL nie osiagnal gotowosci.")

        docker("cp", str(dump), f"{name}:/tmp/restore.dump")
        docker("exec", name, "pg_restore", "--username=postgres", f"--dbname={RESTORE_DB}",
               "--no-owner", "--no-acl", "--single-transaction", "--exit-on-error",
               "/tmp/restore.dump")
        result = docker(*restore_query_args(name))
        counts = json.loads(result.stdout.strip())
        for key in ("scrape_runs", "raw_panels", "silver_panels", "gold_ranking", "gold_history", "gold_daily"):
            if key not in counts or not isinstance(counts[key], int):
                raise BackupError(f"Brak tabeli/widoku lub bledny wynik: {key}")
        if counts["scrape_runs"] <= 0 or counts["raw_panels"] <= 0 or counts["gold_ranking"] <= 0:
            raise BackupError("Baza odtworzona, ale brakuje oczekiwanych danych biznesowych.")
        report = {
            "verified_utc": datetime.now(timezone.utc).isoformat(),
            "result": "PASS", "backup_file": dump.name,
            "sha256": metadata["sha256"], "restored_counts": counts,
            "environment": "disposable isolated postgres:17 container (no published ports)",
        }
        out = dump.with_name(dump.name + ".verified.json")
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("RESTORE PASS — osobny PostgreSQL, bez ingerencji w solar-postgres")
        print(json.dumps(counts, indent=2))
        print(f"Raport weryfikacji: {out}")
        return report
    finally:
        # Even if `docker run` returned an error, it may have created a container.
        if created_volume:
            existing = docker("container", "inspect", name, check=False)
            if existing.returncode == 0:
                cleanup = docker("rm", "-f", name, check=False)
                if cleanup.returncode:
                    print(f"UWAGA: usun recznie kontener testowy {name}: {cleanup.stderr.strip()}", file=sys.stderr)
        if created_volume:
            cleanup = docker("volume", "rm", volume, check=False)
            if cleanup.returncode:
                print(f"UWAGA: usun recznie WYLACZNIE tymczasowy wolumen {volume}: {cleanup.stderr.strip()}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup / isolated restore for E2E Solar PostgreSQL")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="Create pg_dump custom-format backup")
    create.add_argument("--directory", type=Path, default=DEFAULT_BACKUP_DIR)
    create.add_argument("--container", default=DEFAULT_CONTAINER)
    verify = sub.add_parser("verify", help="Verify SHA256 and restore to an isolated DB")
    verify.add_argument("backup", nargs="?", type=Path)
    verify.add_argument("--directory", type=Path, default=DEFAULT_BACKUP_DIR)
    args = parser.parse_args()
    try:
        if args.command == "create":
            create_backup(args.directory, args.container)
        else:
            dump = args.backup or latest_backup(args.directory)
            verify_backup(dump.resolve())
    except (BackupError, OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
