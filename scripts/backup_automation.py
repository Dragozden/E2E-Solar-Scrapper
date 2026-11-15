"""Schedule-ready verified PostgreSQL backup runner for E2E Solar.

This script reuses the manually tested scripts/postgres_backup.py implementation.
It never restores into, deletes, or alters the running PostgreSQL cluster.

Usage (repository root):
    uv run --frozen python scripts/backup_automation.py run
    uv run --frozen python scripts/backup_automation.py run --mirror-dir F:\\SolarBackups --retention-days 90
    uv run --frozen python scripts/backup_automation.py status

Retention is disabled unless a separate mirror directory is configured.
Only *verified* dumps with *matching mirrored copies* may be removed, and at
least four locally verified backups are retained. No pre-existing unknown files
are touched.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Iterator
from uuid import uuid4

# Works when invoked as a script from the repository root and in pytest.
try:
    from scripts.postgres_backup import (
        DEFAULT_BACKUP_DIR,
        BackupError,
        create_backup,
        manifest_path,
        sha256_file,
        validate_manifest,
        verify_backup,
    )
except ModuleNotFoundError:
    from postgres_backup import (  # type: ignore[no-redef]
        DEFAULT_BACKUP_DIR,
        BackupError,
        create_backup,
        manifest_path,
        sha256_file,
        validate_manifest,
        verify_backup,
    )

BACKUP_NAME = re.compile(r"^solar_prices_\d{8}_\d{6}Z_[a-f0-9]{8}\.dump$")
DEFAULT_MIN_KEEP = 4


class AutomationError(RuntimeError):
    """A safety check rejected an operation before destructive work."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def verified_report_path(dump: Path) -> Path:
    return dump.with_name(dump.name + ".verified.json")


def _read_json(path: Path) -> dict:
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise AutomationError(f"JSON is not an object: {path.name}")
    return result


def verified_backup(dump: Path) -> tuple[dict, dict]:
    """Confirm manifest checksum and an existing real restore PASS receipt.

    Never merely trusts a filename or the presence of .verified.json.
    """
    if not BACKUP_NAME.fullmatch(dump.name) or not dump.is_file() or dump.is_symlink():
        raise AutomationError(f"Not a supported backup: {dump.name}")
    metadata = validate_manifest(dump)
    receipt_path = verified_report_path(dump)
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise AutomationError(f"Backup has no verification receipt: {dump.name}")
    receipt = _read_json(receipt_path)
    if (receipt.get("result") != "PASS"
            or receipt.get("backup_file") != dump.name
            or receipt.get("sha256") != metadata["sha256"]):
        raise AutomationError(f"Verification receipt mismatch: {dump.name}")
    restored = receipt.get("restored_counts")
    if not isinstance(restored, dict) or not all(
        isinstance(restored.get(key), int) and restored[key] >= 0
        for key in ("scrape_runs", "raw_panels", "gold_ranking")
    ):
        raise AutomationError(f"Invalid verification metrics: {dump.name}")
    if (restored["scrape_runs"] == 0 or restored["raw_panels"] == 0
            or restored["gold_ranking"] == 0):
        raise AutomationError(f"Empty business data in verification: {dump.name}")
    try:
        created = datetime.fromisoformat(str(metadata["created_utc"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise AutomationError(f"Missing creation date: {dump.name}") from exc
    if created.tzinfo is None:
        raise AutomationError(f"Backup creation date lacks timezone: {dump.name}")
    return metadata, receipt


def _contained(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_mirror_dir(directory: Path, backup_dir: Path) -> Path:
    """Require an existing, separate directory; never create an implicit target."""
    if not directory.exists() or not directory.is_dir() or directory.is_symlink():
        raise AutomationError("Mirror directory must already exist and must not be a symlink")
    mirror, local = directory.resolve(), backup_dir.resolve()
    if _contained(mirror, local) or _contained(local, mirror):
        raise AutomationError("Mirror directory must be separate from the local backup tree")
    return mirror


def _copy_atomic(source: Path, target: Path) -> None:
    """Copy a single file without ever overwriting a conflicting existing file."""
    if target.exists():
        if not target.is_file() or target.is_symlink() or sha256_file(target) != sha256_file(source):
            raise AutomationError(f"Conflicting existing mirror file: {target.name}")
        return
    partial = target.with_name(target.name + ".partial-" + uuid4().hex)
    try:
        with source.open("rb") as inp, partial.open("xb") as out:
            shutil.copyfileobj(inp, out, length=1024 * 1024)
        if sha256_file(partial) != sha256_file(source):
            raise AutomationError(f"Checksum mismatch while mirroring: {source.name}")
        # We refuse replacing an existing mirror file even if another process
        # has raced us: the task lock prevents our own overlapping runs.
        if target.exists():
            raise AutomationError(f"Mirror file appeared during copying: {target.name}")
        partial.rename(target)
    finally:
        partial.unlink(missing_ok=True)


def mirror_verified(dump: Path, mirror_dir: Path, backup_dir: Path) -> Path:
    """Copy the backup, manifest, and verification receipt; hash-verify all."""
    metadata, _ = verified_backup(dump)
    mirror = validate_mirror_dir(mirror_dir, backup_dir)
    sources = (dump, manifest_path(dump), verified_report_path(dump))
    for source in sources:
        if source.is_symlink():
            raise AutomationError(f"Refusing symlink in backup set: {source.name}")
        _copy_atomic(source, mirror / source.name)
    target = mirror / dump.name
    if sha256_file(target) != metadata["sha256"]:
        raise AutomationError(f"Mirror checksum mismatch: {dump.name}")
    return target


def _mirror_is_complete(dump: Path, mirror: Path) -> bool:
    try:
        metadata, _ = verified_backup(dump)
        for source in (dump, manifest_path(dump), verified_report_path(dump)):
            target = mirror / source.name
            if not target.is_file() or target.is_symlink():
                return False
            if sha256_file(source) != sha256_file(target):
                return False
        return sha256_file(mirror / dump.name) == metadata["sha256"]
    except (AutomationError, BackupError, OSError, ValueError, KeyError, json.JSONDecodeError):
        return False


def _verified_candidates(directory: Path) -> list[tuple[datetime, Path]]:
    candidates = []
    for dump in directory.glob("solar_prices_*.dump"):
        if not BACKUP_NAME.fullmatch(dump.name):
            continue
        try:
            metadata, _ = verified_backup(dump)
            created = datetime.fromisoformat(metadata["created_utc"]).astimezone(timezone.utc)
        except (AutomationError, BackupError, OSError, ValueError, KeyError, json.JSONDecodeError):
            # Unknown/corrupt backups must never be silently deleted.
            continue
        candidates.append((created, dump))
    return sorted(candidates, key=lambda pair: (pair[0], pair[1].name), reverse=True)


def retention_plan(
    backup_dir: Path,
    mirror_dir: Path,
    *,
    retention_days: int,
    keep_minimum: int = DEFAULT_MIN_KEEP,
    now: datetime | None = None,
) -> list[Path]:
    """Dry-run: list deletable local archives without deleting anything."""
    if retention_days < 30:
        raise AutomationError("Retention must be >=30 days")
    if keep_minimum < DEFAULT_MIN_KEEP:
        raise AutomationError(f"keep_minimum must be >= {DEFAULT_MIN_KEEP}")
    mirror = validate_mirror_dir(mirror_dir, backup_dir)
    now = now or utc_now()
    if now.tzinfo is None:
        raise AutomationError("now must contain timezone")
    cutoff = now.astimezone(timezone.utc) - timedelta(days=retention_days)
    candidates = _verified_candidates(backup_dir)
    return [dump for created, dump in candidates[keep_minimum:]
            if created < cutoff and _mirror_is_complete(dump, mirror)]


def prune_local_verified(
    backup_dir: Path,
    mirror_dir: Path,
    *,
    retention_days: int,
    keep_minimum: int = DEFAULT_MIN_KEEP,
    now: datetime | None = None,
) -> list[Path]:
    """Delete only old verified LOCAL archives with an intact mirror."""
    eligible = retention_plan(backup_dir, mirror_dir,
                              retention_days=retention_days,
                              keep_minimum=keep_minimum, now=now)
    for dump in eligible:
        # Only strictly recognized files; never folders or other backup formats.
        for path in (verified_report_path(dump), manifest_path(dump), dump):
            path.unlink()
    return eligible


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial-" + uuid4().hex)
    try:
        partial.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)


@contextmanager
def exclusive_run(backup_dir: Path) -> Iterator[None]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    lock_path = backup_dir / ".weekly_backup.lock"
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise AutomationError(
            "Backup already running (or stale lock). Check processes before removing "
            f"{lock_path}"
        ) from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(f"pid={os.getpid()} utc={utc_now().isoformat()}\n")
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def run_automation(
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    *,
    mirror_dir: Path | None = None,
    retention_days: int | None = None,
    keep_minimum: int = DEFAULT_MIN_KEEP,
) -> dict:
    if retention_days is not None and mirror_dir is None:
        raise AutomationError("Retention requires --mirror-dir to preserve another verified copy")
    if retention_days is not None and retention_days < 30:
        raise AutomationError("Retention must be >=30 days")
    if keep_minimum < DEFAULT_MIN_KEEP:
        raise AutomationError(f"keep_minimum must be >= {DEFAULT_MIN_KEEP}")
    backup_dir = backup_dir.resolve()
    report_dir = backup_dir / "status"
    report = {"started_utc": utc_now().isoformat(), "status": "RUNNING"}
    with exclusive_run(backup_dir):
        try:
            # Record a FAIL receipt even if a removable USB mirror is missing.
            # Previously this validation happened before the try/except, so a
            # scheduled run could fail while status still showed an old PASS.
            mirror = validate_mirror_dir(mirror_dir, backup_dir) if mirror_dir else None
            dump = create_backup(backup_dir)
            receipt = verify_backup(dump)
            metadata, confirmed = verified_backup(dump)
            if receipt.get("result") != "PASS" or receipt.get("sha256") != metadata["sha256"]:
                raise AutomationError("Restore verification did not return PASS")
            report.update({"status": "PASS", "completed_utc": utc_now().isoformat(),
                           "backup": dump.name, "sha256": metadata["sha256"],
                           "restored_counts": confirmed["restored_counts"]})
            if mirror:
                target = mirror_verified(dump, mirror, backup_dir)
                report["mirrored_to"] = str(target.parent)
            else:
                report["mirror_warning"] = "Only local copy exists; not protection against disk loss"
            if retention_days is not None:
                removed = prune_local_verified(backup_dir, mirror, retention_days=retention_days,
                                               keep_minimum=keep_minimum)
                report["pruned_local_copies"] = [p.name for p in removed]
            _atomic_json(report_dir / "latest_success.json", report)
        except Exception as exc:
            report.update({"status": "FAIL", "completed_utc": utc_now().isoformat(),
                           "error_type": type(exc).__name__})
            _atomic_json(report_dir / "last_attempt.json", report)
            raise
        _atomic_json(report_dir / "last_attempt.json", report)
        return report


def status(backup_dir: Path) -> dict:
    path = backup_dir / "status" / "last_attempt.json"
    if not path.is_file():
        raise AutomationError("No scheduled backup result yet. Run the backup once.")
    return _read_json(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verified scheduled backups for local E2E Solar")
    subs = parser.add_subparsers(dest="command", required=True)
    run = subs.add_parser("run", help="Create, restore-test, optionally mirror and prune")
    run.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    run.add_argument("--mirror-dir", type=Path, default=None)
    run.add_argument("--retention-days", type=int, default=None)
    run.add_argument("--keep-minimum", type=int, default=DEFAULT_MIN_KEEP)
    show = subs.add_parser("status", help="Print last scheduled backup result (no Docker needed)")
    show.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    plan = subs.add_parser("plan", help="Preview local deletions (never deletes anything)")
    plan.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    plan.add_argument("--mirror-dir", type=Path, required=True)
    plan.add_argument("--retention-days", type=int, required=True)
    plan.add_argument("--keep-minimum", type=int, default=DEFAULT_MIN_KEEP)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            result = run_automation(args.backup_dir, mirror_dir=args.mirror_dir,
                                    retention_days=args.retention_days,
                                    keep_minimum=args.keep_minimum)
        elif args.command == "plan":
            eligible = retention_plan(args.backup_dir, args.mirror_dir,
                                      retention_days=args.retention_days,
                                      keep_minimum=args.keep_minimum)
            result = {"status": "PASS", "dry_run": True,
                      "would_delete_local": [p.name for p in eligible]}
        else:
            result = status(args.backup_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") == "PASS" else 1
    except (AutomationError, BackupError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"BACKUP AUTOMATION ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
