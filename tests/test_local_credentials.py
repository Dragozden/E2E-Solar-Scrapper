"""Offline tests; never connect to an actual PostgreSQL database."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from scripts.local_credentials import (
    CredentialError, atomic_secret_write, check_verified_backup,
    compose_content, initialize, update_root_password,
)


def test_password_update_preserves_other_secrets():
    original = "POSTGRES_PASSWORD=old\nSOLAR_ALERT_WEBHOOK_URL=private-url\nPOSTGRES_HOST=localhost\n"
    new = update_root_password(original, "new-random-value")
    assert "POSTGRES_PASSWORD=new-random-value" in new
    assert "SOLAR_ALERT_WEBHOOK_URL=private-url" in new
    assert "POSTGRES_PASSWORD=old" not in new


def test_root_password_requires_exactly_one_assignment():
    with pytest.raises(CredentialError, match="exactly one"):
        update_root_password("POSTGRES_HOST=localhost\n", "abc")
    with pytest.raises(CredentialError, match="exactly one"):
        update_root_password("POSTGRES_PASSWORD=a\nPOSTGRES_PASSWORD=b\n", "abc")


def test_compose_passwords_are_distinct():
    text = compose_content("secret-pg", "secret-pgadmin")
    assert "POSTGRES_PASSWORD=secret-pg\n" in text
    assert "PGADMIN_DEFAULT_PASSWORD=secret-pgadmin\n" in text


def test_atomic_secret_write_and_no_temp_leftover(tmp_path):
    file = tmp_path / ".env"
    atomic_secret_write(file, "POSTGRES_PASSWORD=one\n")
    atomic_secret_write(file, "POSTGRES_PASSWORD=two\n")
    assert file.read_text() == "POSTGRES_PASSWORD=two\n"
    assert not (tmp_path / ".env.pending").exists()


def test_atomic_refuses_stale_pending(tmp_path):
    file = tmp_path / ".env"
    (tmp_path / ".env.pending").write_text("unexpected")
    with pytest.raises(CredentialError, match="Stale pending"):
        atomic_secret_write(file, "new")


def test_init_creates_two_files_and_refuses_overwrite(tmp_path):
    (tmp_path / "docker").mkdir()
    (tmp_path / ".env.example").write_text(
        "POSTGRES_HOST=localhost\nPOSTGRES_DB=solar_prices\nPOSTGRES_USER=postgres\nPOSTGRES_PASSWORD=placeholder\n"
    )
    initialize(tmp_path)
    root = (tmp_path / ".env").read_text()
    compose = (tmp_path / "docker" / ".env").read_text()
    assert "placeholder" not in root
    assert "placeholder" not in compose
    assert "PGADMIN_DEFAULT_PASSWORD=" in compose
    with pytest.raises(CredentialError, match="Existing credentials"):
        initialize(tmp_path)


def test_backup_requires_verified_manifest(tmp_path):
    (tmp_path / "solar_prices_20261115_000000Z_a.dump").write_bytes(b"sample-dump")
    with pytest.raises(CredentialError, match="No recent verified"):
        check_verified_backup(tmp_path)


def test_backup_sha256_and_restore_report(tmp_path):
    dump = tmp_path / "solar_prices_20261115_000000Z_a.dump"
    dump.write_bytes(b"sample-dump")
    digest = hashlib.sha256(dump.read_bytes()).hexdigest()
    (tmp_path / (dump.name + ".json")).write_text(json.dumps({
        "format": "pg_dump-custom", "sha256": digest, "size_bytes": dump.stat().st_size
    }))
    (tmp_path / (dump.name + ".verified.json")).write_text(json.dumps({
        "result": "PASS", "sha256": digest,
        "verified_utc": datetime.now(timezone.utc).isoformat(),
    }))
    assert check_verified_backup(tmp_path) == dump
    dump.write_bytes(b"corrupted")
    with pytest.raises(CredentialError, match="No recent verified"):
        check_verified_backup(tmp_path)


def test_compose_requires_secrets_and_keeps_local_ports():
    root = Path(__file__).resolve().parents[1]
    base = yaml.safe_load((root / "docker/docker-compose.yml").read_text())
    assert "${POSTGRES_PASSWORD:?" in base["services"]["postgres"]["environment"]["POSTGRES_PASSWORD"]
    assert "${PGADMIN_DEFAULT_PASSWORD:?" in base["services"]["pgadmin"]["environment"]["PGADMIN_DEFAULT_PASSWORD"]
    assert base["services"]["postgres"]["ports"] == ["127.0.0.1:5432:5432"]
    assert base["services"]["pgadmin"]["ports"] == ["127.0.0.1:5050:80"]

class _FakeCursor:
    def __init__(self):
        self.query = ""
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, query, *args):
        self.query = str(query)
    def fetchone(self):
        return ("postgres",) if "current_user" in self.query else (1,)

class _FakeConnection:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def cursor(self): return _FakeCursor()


def _rotation_files(tmp_path):
    (tmp_path / "docker").mkdir()
    (tmp_path / ".env").write_text(
        "POSTGRES_HOST=localhost\nPOSTGRES_USER=postgres\nPOSTGRES_DB=solar_prices\n"
        "POSTGRES_PASSWORD=old-password\nSOLAR_ALERT_WEBHOOK_URL=keep-this-private\n"
    )
    (tmp_path / "docker" / ".env").write_text(
        "POSTGRES_PASSWORD=old-password\nPGADMIN_DEFAULT_PASSWORD=old-admin-password\n"
    )


def test_rotate_updates_database_and_two_files_without_changing_webhook(tmp_path, monkeypatch):
    import scripts.local_credentials as mod
    _rotation_files(tmp_path)
    changes = []
    monkeypatch.setattr(mod, "db_connect", lambda *a, **kw: _FakeConnection())
    monkeypatch.setattr(mod, "check_verified_backup", lambda *a, **kw: tmp_path / "validated.dump")
    monkeypatch.setattr(mod, "change_role_password", lambda conn, role, value: changes.append((role, value)))
    mod.rotate(tmp_path)
    root = (tmp_path / ".env").read_text()
    compose = (tmp_path / "docker" / ".env").read_text()
    assert "POSTGRES_PASSWORD=old-password" not in root
    assert "SOLAR_ALERT_WEBHOOK_URL=keep-this-private" in root
    assert mod.env_value(tmp_path / ".env", "POSTGRES_PASSWORD") == mod.env_value(tmp_path / "docker" / ".env", "POSTGRES_PASSWORD")
    assert changes[0][0] == "postgres"
    assert changes[0][1] != "old-password"
    assert len(changes) == 1


def test_rotate_attempts_rollback_on_local_secret_write_failure(tmp_path, monkeypatch):
    import scripts.local_credentials as mod
    _rotation_files(tmp_path)
    root_file = tmp_path / ".env"
    compose_file = tmp_path / "docker" / ".env"
    root_before, compose_before = root_file.read_text(), compose_file.read_text()
    changes = []
    monkeypatch.setattr(mod, "db_connect", lambda *a, **kw: _FakeConnection())
    monkeypatch.setattr(mod, "check_verified_backup", lambda *a, **kw: tmp_path / "validated.dump")
    monkeypatch.setattr(mod, "change_role_password", lambda conn, role, value: changes.append(value))
    original = mod.atomic_secret_write
    fail_first_compose = {"pending": True}
    def fake_write(path, contents):
        if path == compose_file and fail_first_compose["pending"]:
            fail_first_compose["pending"] = False
            raise OSError("simulated disk error")
        return original(path, contents)
    monkeypatch.setattr(mod, "atomic_secret_write", fake_write)
    with pytest.raises(CredentialError, match="rollback attempted"):
        mod.rotate(tmp_path)
    assert root_file.read_text() == root_before
    assert compose_file.read_text() == compose_before
    assert len(changes) == 2
    assert changes[-1] == "old-password"
