"""Read-only local security preflight for the E2E Solar development stack.

Run from repo root: uv run python scripts/security_audit.py
Optional: --strict treats all detected warnings as a failing preflight.
Never prints secret values, opens a database connection, or changes services.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docker" / "docker-compose.yml"
OVERLAY = ROOT / "docker" / "docker-compose.override.yml"


def listen_address(port_spec: object) -> str:
    """Return the host portion of Compose's short port syntax."""
    if isinstance(port_spec, str) and port_spec.count(":") >= 2:
        return port_spec.rsplit(":", 2)[0].strip("[]")
    if isinstance(port_spec, dict):
        return str(port_spec.get("host_ip", "0.0.0.0"))
    return "0.0.0.0"


def local_bind_warnings(*configs: dict) -> list[str]:
    warnings = []
    for config in configs:
        for service, entry in config.get("services", {}).items():
            for port in entry.get("ports", []):
                host = listen_address(port)
                if host not in ("127.0.0.1", "::1", "localhost"):
                    warnings.append(f"Port exposed beyond localhost: {service} (review ports)")
    return warnings


def credential_warnings(config: dict) -> list[str]:
    services = config.get("services", {})
    postgres_env = services.get("postgres", {}).get("environment", {})
    pgadmin_env = services.get("pgadmin", {}).get("environment", {})
    warnings = []
    if postgres_env.get("POSTGRES_PASSWORD") == "postgres":
        warnings.append("PostgreSQL uses example development password")
    if pgadmin_env.get("PGADMIN_DEFAULT_PASSWORD") == "admin":
        warnings.append("pgAdmin uses example development password")
    return warnings


def tracked_sensitive_files(repo: Path) -> list[str]:
    proc = subprocess.run(["git", "ls-files", "-z"], cwd=repo, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=False)
    if proc.returncode:
        raise RuntimeError("git ls-files failed: run from a Git worktree")
    paths = [x.decode("utf-8", errors="replace").replace("\\", "/")
             for x in proc.stdout.split(b"\0") if x]
    flagged = []
    for path in paths:
        parts = Path(path).parts
        name = Path(path).name
        if (name == ".env" or (name.startswith(".env.") and name != ".env.example")
                or name.endswith((".dump", ".backup", ".sql.gz"))
                or (parts and parts[0] == "backups")):
            flagged.append(path)
    return flagged


def audit(repo: Path = ROOT) -> list[str]:
    base = yaml.safe_load((repo / "docker" / "docker-compose.yml").read_text(encoding="utf-8"))
    overlay = yaml.safe_load((repo / "docker" / "docker-compose.override.yml").read_text(encoding="utf-8"))
    warnings = local_bind_warnings(base, overlay) + credential_warnings(base)
    tracked = tracked_sensitive_files(repo)
    if tracked:
        # File paths, never file contents.
        warnings.append("Sensitive files tracked by Git: " + ", ".join(tracked))
    ignore = (repo / ".gitignore").read_text(encoding="utf-8-sig")
    dockerignore = (repo / ".dockerignore").read_text(encoding="utf-8-sig")
    if "backups/" not in ignore:
        warnings.append(".gitignore does not exclude backups/")
    if "backups/" not in dockerignore:
        warnings.append(".dockerignore does not exclude backups/")
    return warnings


def main() -> None:
    parser = argparse.ArgumentParser(description="Non-destructive security audit")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if any warning exists")
    args = parser.parse_args()
    warnings = audit()
    if not warnings:
        print("PASS: No preflight warnings detected.")
    else:
        print(f"Preflight: {len(warnings)} warning(s). Local development is not public-deploy ready:")
        for warning in warnings:
            print(f"  WARN: {warning}")
    if warnings and args.strict:
        parser.exit(1)


if __name__ == "__main__":
    main()
