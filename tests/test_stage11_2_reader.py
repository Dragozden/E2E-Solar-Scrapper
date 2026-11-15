"""Offline tests for Gold technical comparison read-only privileges."""
from __future__ import annotations

import sys
from types import ModuleType

import pytest

from scripts import grant_panel_comparison_reader as grants


def make_envs(tmp_path, *, user="solar_dashboard"):
    (tmp_path / "dashboard").mkdir(exist_ok=True)
    (tmp_path / ".env").write_text(
        "POSTGRES_HOST=localhost\nPOSTGRES_PORT=5432\nPOSTGRES_DB=solar_prices\n"
        "POSTGRES_USER=postgres\nPOSTGRES_PASSWORD=fake_admin\n", encoding="utf-8"
    )
    (tmp_path / "dashboard" / ".env").write_text(
        "POSTGRES_HOST=postgres\nPOSTGRES_PORT=5432\nPOSTGRES_DB=solar_prices\n"
        f"POSTGRES_USER={user}\nPOSTGRES_PASSWORD=fake_reader\n", encoding="utf-8"
    )


def test_reader_uses_localhost_connection_and_read_only(tmp_path, monkeypatch):
    make_envs(tmp_path)
    monkeypatch.setattr(grants, "ROOT", tmp_path)
    admin, reader = grants.credentials()
    assert admin["password"] == "fake_admin"
    assert reader["password"] == "fake_reader"
    assert reader["host"] == "localhost"  # dashboard/.env has container-only hostname
    assert reader["user"] == "solar_dashboard"
    assert reader["options"] == "-c default_transaction_read_only=on"


def test_wrong_dashboard_role_rejected(tmp_path, monkeypatch):
    make_envs(tmp_path, user="postgres")
    monkeypatch.setattr(grants, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="dedicated"):
        grants.credentials()


def test_no_envs_created_on_missing_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(grants, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="Missing"):
        grants.credentials()
    assert list(tmp_path.iterdir()) == []


def fake_psycopg(monkeypatch, *, exists=True, role=True, read_only=True):
    calls = []
    rows = []

    class Cursor:
        def execute(self, statement):
            calls.append(statement)
            if "FROM pg_class" in statement:
                rows.append((exists,))
            elif "FROM pg_roles" in statement:
                rows.append((role,))
            elif statement.startswith("SHOW"):
                rows.append(("on" if read_only else "off",))
            elif statement.startswith("SELECT COUNT"):
                rows.append((72,))

        def fetchone(self):
            return rows.pop(0)

        def __enter__(self): return self
        def __exit__(self, *_): pass

    class Conn:
        def cursor(self): return Cursor()
        def __enter__(self): return self
        def __exit__(self, *_): pass

    module = ModuleType("psycopg")
    module.connect = lambda **kwargs: Conn()
    monkeypatch.setitem(sys.modules, "psycopg", module)
    return calls


def test_grant_is_select_only_and_checks_view_exists(monkeypatch):
    calls = fake_psycopg(monkeypatch)
    grants.grant({"dbname": "solar_prices"})
    assert "GRANT USAGE ON SCHEMA gold TO solar_dashboard" in calls
    assert "GRANT SELECT ON gold.panel_technical_comparison TO solar_dashboard" in calls
    assert not any("ALTER ROLE" in query or "DELETE " in query for query in calls)


def test_grant_refuses_missing_view(monkeypatch):
    calls = fake_psycopg(monkeypatch, exists=False)
    with pytest.raises(RuntimeError, match="run dbt build first"):
        grants.grant({})
    assert not any("GRANT" in query for query in calls)


def test_grant_refuses_missing_role(monkeypatch):
    calls = fake_psycopg(monkeypatch, role=False)
    with pytest.raises(RuntimeError, match="Missing solar_dashboard"):
        grants.grant({})
    assert not any("GRANT" in query for query in calls)


def test_check_uses_read_only_session(monkeypatch):
    calls = fake_psycopg(monkeypatch)
    assert grants.check({"options": "-c default_transaction_read_only=on"}) == 72
    assert calls == ["SHOW transaction_read_only", "SELECT COUNT(*) FROM gold.panel_technical_comparison"]


def test_check_rejects_writable_session(monkeypatch):
    calls = fake_psycopg(monkeypatch, read_only=False)
    with pytest.raises(RuntimeError, match="not read-only"):
        grants.check({})
    assert calls == ["SHOW transaction_read_only"]
