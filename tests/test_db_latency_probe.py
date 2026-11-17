"""No PostgreSQL required: conservative performance diagnosis contract."""
from __future__ import annotations

from types import SimpleNamespace
import sys

import pytest

from scripts import diagnose_db_latency as probe


def test_ipv4_only_local():
    assert probe.ipv4_host("localhost") == "127.0.0.1"
    assert probe.ipv4_host("127.0.0.1") == "127.0.0.1"
    for host in ("postgres", "10.0.0.1", "example.com", None):
        with pytest.raises(ValueError):
            probe.ipv4_host(host)


def test_sql_queries_are_select_only():
    assert len(probe.QUERIES) == 5
    assert all(sql.lstrip().upper().startswith("SELECT") for _, sql in probe.QUERIES)
    plan = probe.QUERIES[-1][1]
    assert "gold.current_panel_ranking" in plan
    assert "bronze.panel_spec_snapshots" in plan
    assert "bronze.panel_spec_attempts" in plan


def test_timing_reports_success_and_failure():
    messages = []
    assert probe.timed("fast", lambda: 42, emit=messages.append) == 42
    assert messages[0].startswith("TIME fast:")
    with pytest.raises(RuntimeError):
        probe.timed("broken", lambda: (_ for _ in ()).throw(RuntimeError()), emit=messages.append)
    assert messages[-1].startswith("FAIL broken:")


def test_readonly_cursor_execution_and_row_count():
    class Cursor:
        def execute(self, sql):
            assert sql == "SELECT 1"
        def fetchall(self):
            return [(1,)]
        def __enter__(self): return self
        def __exit__(self, *exc): return None
    msgs=[]
    assert probe.timed_query(SimpleNamespace(cursor=Cursor), "ping", "SELECT 1", emit=msgs.append) == 1
    assert "  rows=1" in msgs


def test_probe_connection_options_are_bounded_and_compatible(monkeypatch):
    # No importing psycopg package or hitting a live database.
    from scraper import config as cfg
    fake_calls = []
    class FakePG:
        def connect(self, **options):
            fake_calls.append(options)
            return options
    monkeypatch.setitem(sys.modules, "psycopg", FakePG())
    # Import after replacement; test the parameter builder, independent of driver.
    import scraper.load as load
    monkeypatch.setenv("SOLAR_DB_CONNECT_TIMEOUT", "10")
    options=load.connection_kwargs()
    assert options["connect_timeout"] == 10
    assert options["host"] == cfg.config.host
    assert options["user"] == cfg.config.user
    assert load.get_connection() == options
    assert fake_calls == [options]


@pytest.mark.parametrize("value", ["0", "2", "61", "bad", "3.5", "-9"])
def test_invalid_timeout_rejected(monkeypatch, value):
    import scraper.load as load
    monkeypatch.setenv("SOLAR_DB_CONNECT_TIMEOUT", value)
    with pytest.raises(ValueError, match="SOLAR_DB_CONNECT_TIMEOUT"):
        load.connection_kwargs()


def test_default_timeout(monkeypatch):
    import scraper.load as load
    monkeypatch.delenv("SOLAR_DB_CONNECT_TIMEOUT", raising=False)
    assert load.connection_kwargs()["connect_timeout"] == 10
