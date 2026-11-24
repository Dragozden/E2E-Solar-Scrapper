"""Read-only local security preflight. Never prints secrets or modifies services."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docker" / "docker-compose.yml"
OVERLAY = ROOT / "docker" / "docker-compose.override.yml"


def listen_address(port_spec: object) -> str:
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


def local_secret_warnings(repo: Path) -> list[str]:
    root_env, compose_env = repo / ".env", repo / "docker" / ".env"
    warnings = []
    if not root_env.is_file() or not compose_env.is_file():
        warnings.append("Missing root .env or docker/.env; run local_credentials init/rotate")
        return warnings
    root = dotenv_values(root_env)
    compose = dotenv_values(compose_env)
    pg_root, pg_compose, pgadmin = root.get("POSTGRES_PASSWORD"), compose.get("POSTGRES_PASSWORD"), compose.get("PGADMIN_DEFAULT_PASSWORD")
    if not pg_root or not pg_compose or pg_root != pg_compose:
        warnings.append("Root and Compose PostgreSQL credentials missing or inconsistent")
    if pg_root == "postgres" or pg_compose == "postgres":
        warnings.append("PostgreSQL uses example development password")
    if pgadmin == "admin" or not pgadmin:
        warnings.append("pgAdmin uses example development password or missing secret")
    for key, value in (("PostgreSQL", pg_compose), ("pgAdmin", pgadmin)):
        if value and len(value) < 24 and value not in ("postgres", "admin"):
            warnings.append(f"{key} local password is shorter than 24 characters")
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
    warnings += local_secret_warnings(repo)
    tracked = tracked_sensitive_files(repo)
    if tracked:
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
