"""Read-only local acceptance checks for the E2E Solar Docker deployment.

Run from project root:
    uv run --frozen python scripts/local_release_check.py --mirror-dir F:\\SolarBackups

Does not invoke the live scraper, rebuild dbt, modify databases, copy backups,
run migrations, remove volumes or change credentials. Non-zero exit on FAIL.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

try:
    from scripts.backup_automation import _mirror_is_complete, verified_backup, validate_mirror_dir
except ModuleNotFoundError:  # python scripts/local_release_check.py
    from backup_automation import _mirror_is_complete, verified_backup, validate_mirror_dir

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CONTAINERS = (
    "solar-postgres", "solar-airflow", "solar-dashboard", "solar-pgadmin"
)
MAIN_DAG = "solar_el_pipeline"
WATCHDOG_DAG = "solar_data_watchdog"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str

    def __post_init__(self) -> None:
        if self.status not in {"PASS", "WARN", "FAIL"}:
            raise ValueError("Unknown check state")


def run_command(arguments: list[str], *, timeout: int = 45) -> subprocess.CompletedProcess[str]:
    """No shell, no secret arguments and no command output to a file."""
    return subprocess.run(arguments, cwd=ROOT, text=True, encoding="utf-8",
                          errors="replace", capture_output=True, timeout=timeout, check=False)


def classify_container_state(name: str, state: dict) -> Check:
    if state.get("Status") != "running":
        return Check(name, "FAIL", f"Container state: {state.get('Status', 'unknown')}")
    health = state.get("Health", {}).get("Status") if isinstance(state.get("Health"), dict) else None
    if health == "unhealthy":
        return Check(name, "FAIL", "Container unhealthy")
    if health == "starting":
        return Check(name, "WARN", "Healthcheck still starting")
    if name == "solar-postgres" and health != "healthy":
        return Check(name, "WARN", "PostgreSQL has no healthy healthcheck status")
    return Check(name, "PASS", "Container running" + (", healthy" if health == "healthy" else ""))


def inspect_containers() -> list[Check]:
    results = []
    for name in EXPECTED_CONTAINERS:
        try:
            result = run_command(["docker", "inspect", "--format", "{{json .State}}", name])
            if result.returncode:
                results.append(Check(name, "FAIL", "Container missing or docker inspect failed"))
            else:
                results.append(classify_container_state(name, json.loads(result.stdout)))
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
            results.append(Check(name, "FAIL", "Cannot inspect container state"))
    return results


def check_dashboard_http() -> Check:
    url = "http://127.0.0.1:8501/_stcore/health"
    try:
        with urlopen(url, timeout=6) as response:
            code = response.status
    except (OSError, HTTPError, URLError, TimeoutError):
        return Check("Streamlit HTTP", "FAIL", "Health endpoint unavailable")
    return Check("Streamlit HTTP", "PASS" if code == 200 else "FAIL", f"HTTP {code}")


def check_airflow_dags() -> Check:
    try:
        result = run_command(["docker", "exec", "solar-airflow", "airflow", "dags", "list"], timeout=40)
    except (OSError, subprocess.TimeoutExpired):
        return Check("Airflow DAGs", "FAIL", "Cannot list DAGs")
    if result.returncode:
        return Check("Airflow DAGs", "FAIL", f"airflow dags list exited {result.returncode}")
    missing = [name for name in (MAIN_DAG, WATCHDOG_DAG) if name not in result.stdout]
    if missing:
        return Check("Airflow DAGs", "FAIL", "Not registered: " + ", ".join(missing))
    return Check("Airflow DAGs", "PASS", "Main pipeline and watchdog registered")


def check_reader_permissions() -> Check:
    try:
        result = run_command([sys.executable, str(ROOT / "scripts" / "repair_dashboard_permissions.py"), "--check"])
    except (OSError, subprocess.TimeoutExpired):
        return Check("Dashboard DB reader", "FAIL", "Cannot run SELECT-only check")
    if result.returncode or "READER PASS" not in result.stdout:
        return Check("Dashboard DB reader", "FAIL", "Reader verification failed; run repair_dashboard_permissions.py --check")
    return Check("Dashboard DB reader", "PASS", "SELECT to Bronze/Gold, read-only")


def check_watchdog() -> Check:
    try:
        result = run_command(["docker", "exec", "solar-airflow", "/opt/airflow/solar-venv/bin/python",
                              "-m", "scraper.watchdog"], timeout=45)
    except (OSError, subprocess.TimeoutExpired):
        return Check("Bronze/Gold freshness", "FAIL", "Cannot execute read-only watchdog")
    if result.returncode or "WATCHDOG PASS" not in result.stdout:
        return Check("Bronze/Gold freshness", "FAIL", "Watchdog check failed; inspect its Airflow logs")
    return Check("Bronze/Gold freshness", "PASS", "Latest ingestion and Gold view healthy")


def backup_recency_check(report: dict, *, now: datetime, max_age_days: int) -> Check:
    if report.get("status") != "PASS":
        return Check("Verified backup", "FAIL", "Last scheduled backup attempt did not PASS")
    try:
        completed = datetime.fromisoformat(report["completed_utc"])
        if completed.tzinfo is None or now.tzinfo is None:
            raise ValueError("Missing timezone")
        age_days = (now - completed).total_seconds() / 86400
    except (KeyError, TypeError, ValueError):
        return Check("Verified backup", "FAIL", "Invalid completion timestamp")
    if age_days < -1 / 24:
        return Check("Verified backup", "FAIL", "Completion time is in the future")
    if age_days > max_age_days:
        return Check("Verified backup", "FAIL", f"Last backup is {age_days:.1f} days old")
    if not report.get("backup"):
        return Check("Verified backup", "FAIL", "Missing backup filename")
    return Check("Verified backup", "PASS", f"Last PASS {age_days:.1f} days ago")


def check_backup(backup_dir: Path, mirror_dir: Path | None, *, max_age_days: int = 8) -> list[Check]:
    report_path = backup_dir / "status" / "last_attempt.json"
    if not report_path.is_file():
        return [Check("Verified backup", "FAIL", "No last_attempt.json; run backup_automation.py run")]
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("Not an object")
    except (OSError, ValueError):
        return [Check("Verified backup", "FAIL", "Unreadable last_attempt.json")]

    freshness = backup_recency_check(report, now=datetime.now(timezone.utc), max_age_days=max_age_days)
    if freshness.status != "PASS":
        return [freshness]

    dump = backup_dir / str(report["backup"])
    try:
        metadata, receipt = verified_backup(dump)
        if metadata.get("sha256") != report.get("sha256") or receipt.get("result") != "PASS":
            raise ValueError("Manifest and receipt mismatch")
    except (OSError, ValueError, KeyError, RuntimeError):
        return [Check("Verified backup", "FAIL", "Dump/manifest/restore receipt validation failed")]
    checks = [freshness]
    if mirror_dir is None:
        checks.append(Check("USB mirror", "WARN", "Not checked; add --mirror-dir F:\\SolarBackups"))
    else:
        try:
            mirror = validate_mirror_dir(mirror_dir, backup_dir)
            mirrored = _mirror_is_complete(dump, mirror)
        except (OSError, ValueError, RuntimeError):
            mirrored = False
        checks.append(Check("USB mirror", "PASS" if mirrored else "FAIL",
                            "Verified set exists on separate path" if mirrored else "Missing or different mirrored backup"))
    return checks


def all_checks(backup_dir: Path, mirror_dir: Path | None, *, max_age_days: int) -> list[Check]:
    return (inspect_containers() + [check_dashboard_http(), check_airflow_dags(),
            check_reader_permissions(), check_watchdog()] +
            check_backup(backup_dir, mirror_dir, max_age_days=max_age_days))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only E2E Solar local deployment acceptance check")
    parser.add_argument("--backup-dir", type=Path, default=ROOT / "backups")
    parser.add_argument("--mirror-dir", type=Path, help="Optional USB backup mirror directory")
    parser.add_argument("--max-backup-age-days", type=int, default=8)
    args = parser.parse_args(argv)
    if args.max_backup_age_days < 1:
        parser.error("--max-backup-age-days must be >= 1")
    checks = all_checks(args.backup_dir, args.mirror_dir, max_age_days=args.max_backup_age_days)
    for item in checks:
        print(f"{item.status:4}  {item.name}: {item.detail}")
    failures = sum(item.status == "FAIL" for item in checks)
    warnings = sum(item.status == "WARN" for item in checks)
    print(f"SUMMARY: {len(checks) - failures - warnings} PASS, {warnings} WARN, {failures} FAIL")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
