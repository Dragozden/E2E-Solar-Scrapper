"""Offline command and DAG contract tests; no Airflow or database required."""
import ast
import importlib.util
from pathlib import Path
import subprocess

import pytest

DAGS = Path(__file__).resolve().parents[1] / "airflow" / "dags"
SPEC = importlib.util.spec_from_file_location("enrichment_commands", DAGS / "solar_spec_enrichment_commands.py")
C = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C)
LIVE = {"confirm_source_access": True, "confirm_no_parallel_scrape": True}


def test_default_plan():
    assert C.plan_command() == [C.PYTHON, "-u", C.BATCH, "plan", "--limit", "5"]
    assert C.batch_command() is None


def test_preview_no_write():
    cmd = C.batch_command({**LIVE, "mode": "preview", "limit": 2})
    assert cmd == [C.PYTHON, "-u", C.BATCH, "run", "--limit", "2", "--delay-seconds", "10"]


def test_write_explicit():
    assert C.batch_command({**LIVE, "mode": "write", "limit": 10})[-1] == "--write"


@pytest.mark.parametrize("conf", [
    {"mode": "write"}, {"mode": "preview", "confirm_source_access": True},
    {"mode": "write", "confirm_no_parallel_scrape": True},
    {"mode": "unknown"}, {"mode": []}, {"limit": 0}, {"limit": 11},
    {"limit": True}, {"limit": "2"}, {"limit": 2.0},
    {"confirm_source_access": "true"}, {"confirm_no_parallel_scrape": 1},
    {"retry_incomplete": True}, {"delay_seconds": 0},
    {"mode": "write; anything"}, [],
])
def test_invalid_config(conf):
    with pytest.raises(ValueError):
        C.plan_command(conf)


def test_check_readonly():
    assert C.check_commands() == [[C.PYTHON, "-u", C.CHECK], [C.PYTHON, "-u", C.BATCH, "status"]]


def test_subprocess_failure_propagates(monkeypatch):
    def run(cmd, **kw):
        assert kw["check"] is True
        assert kw["cwd"] == C.ROOT
        assert kw["env"]["PYTHONPATH"] == C.ROOT
        assert kw["timeout"] == 120
        assert not kw.get("shell", False)
        raise subprocess.CalledProcessError(1, cmd)
    monkeypatch.setattr(C.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        C.run_command(C.plan_command(), timeout=120)


def test_dag_manual_no_retries():
    tree = ast.parse((DAGS / "solar_spec_enrichment.py").read_text(encoding="utf-8"))
    definition = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "solar_spec_enrichment")
    options = {k.arg: k.value for k in definition.decorator_list[0].keywords}
    assert ast.literal_eval(options["schedule"]) is None
    assert ast.literal_eval(options["catchup"]) is False
    assert ast.literal_eval(options["max_active_runs"]) == 1
    assert ast.literal_eval(options["is_paused_upon_creation"]) is True
    assert ast.literal_eval(options["default_args"]) == {"retries": 0}
    assert "plan_batch() >> enrich_batch() >> validate_coverage()" in ast.unparse(definition)
