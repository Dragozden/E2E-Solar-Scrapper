"""Offline-testable command construction for the manual enrichment DAG."""
from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping

ROOT = "/opt/airflow/solar"
PYTHON = "/opt/airflow/solar-venv/bin/python"
BATCH = f"{ROOT}/scripts/panel_spec_batch.py"
CHECK = f"{ROOT}/scripts/check_panel_spec_models.py"
DEFAULTS = {"mode": "plan", "limit": 5, "confirm_source_access": False,
            "confirm_no_parallel_scrape": False}


def validate_config(conf: Mapping | None = None) -> dict:
    if conf is None:
        conf = {}
    if not isinstance(conf, Mapping) or set(conf) - set(DEFAULTS):
        raise ValueError("Unsupported enrichment configuration keys")
    cfg = {**DEFAULTS, **conf}
    if cfg["mode"] not in ("plan", "preview", "write"):
        raise ValueError("mode must be plan, preview or write")
    if type(cfg["limit"]) is not int or not 1 <= cfg["limit"] <= 10:
        raise ValueError("limit must be an integer between 1 and 10")
    for name in ("confirm_source_access", "confirm_no_parallel_scrape"):
        if type(cfg[name]) is not bool:
            raise ValueError(f"{name} must be a boolean")
        if cfg["mode"] != "plan" and not cfg[name]:
            raise ValueError(f"Live mode requires {name}=true")
    return cfg


def plan_command(conf: Mapping | None = None) -> list[str]:
    cfg = validate_config(conf)
    return [PYTHON, "-u", BATCH, "plan", "--limit", str(cfg["limit"])]


def batch_command(conf: Mapping | None = None) -> list[str] | None:
    cfg = validate_config(conf)
    if cfg["mode"] == "plan":
        return None
    cmd = [PYTHON, "-u", BATCH, "run", "--limit", str(cfg["limit"]),
           "--delay-seconds", "10"]
    if cfg["mode"] == "write":
        cmd.append("--write")
    return cmd


def check_commands() -> list[list[str]]:
    return [[PYTHON, "-u", CHECK], [PYTHON, "-u", BATCH, "status"]]


def run_command(command: list[str], *, timeout: int = 600) -> None:
    # No shell, no interpolation from trigger input other than validated limit.
    env = os.environ.copy()
    env["PYTHONPATH"] = ROOT
    subprocess.run(command, cwd=ROOT, env=env, check=True, timeout=timeout)
