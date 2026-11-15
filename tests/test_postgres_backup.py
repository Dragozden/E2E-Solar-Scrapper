"""Offline safety and checksum tests: no Docker daemon or real database needed."""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from scripts import postgres_backup as backup


def proc(*, out="", err="", code=0):
    return subprocess.CompletedProcess(["docker"], code, out, err)


@pytest.mark.parametrize("name", ["postgres", "solar_prices", "_test_12", "Solar_2026"])
def test_valid_database_names(name):
    assert backup.safe_db_name(name) == name


@pytest.mark.parametrize("name", ["bad-name", "foo; DROP DATABASE", "", "  postgres", "with space"])
def test_invalid_database_names(name):
    with pytest.raises(backup.BackupError):
        backup.safe_db_name(name)


def prepare_valid_dump(tmp_path, content=b"mock database dump"):
    dump = tmp_path / "solar_prices_20261115_180000Z_abcd1234.dump"
    dump.write_bytes(content)
    metadata = {"format": "pg_dump-custom", "size_bytes": dump.stat().st_size,
                "sha256": backup.sha256_file(dump)}
    backup.manifest_path(dump).write_text(json.dumps(metadata), encoding="utf-8")
    return dump


def test_valid_checksum(tmp_path):
    dump = prepare_valid_dump(tmp_path)
    assert backup.validate_manifest(dump)["sha256"] == backup.sha256_file(dump)


def test_tampered_backup_is_rejected(tmp_path):
    dump = prepare_valid_dump(tmp_path)
    dump.write_bytes(b"malicious or corrupted bytes")
    with pytest.raises(backup.BackupError, match="SHA256"):
        backup.validate_manifest(dump)


def test_missing_manifest_is_rejected(tmp_path):
    dump = tmp_path / "solar_prices_0000.dump"
    dump.write_bytes(b"data")
    with pytest.raises(backup.BackupError, match="metadanych"):
        backup.validate_manifest(dump)


def test_latest_backup_selection(tmp_path):
    earlier = prepare_valid_dump(tmp_path)
    os.utime(earlier, (time.time() - 30, time.time() - 30))
    later = tmp_path / "solar_prices_later.dump"
    later.write_bytes(b"later")
    assert backup.latest_backup(tmp_path) == later


def test_restore_container_has_no_published_ports_or_production_network():
    args = backup.restore_run_args("solar-restore-verify-123", "solar-restore-verify-data-123", "randompassword")
    assert args[:2] == ["run", "-d"]
    assert args[args.index("--network") + 1] == "none"
    assert "-p" not in args and "--publish" not in args
    assert "solar-postgres" not in args
    assert "solar_restore" in " ".join(args)
    assert "postgres:17" == args[-1]


def test_restore_query_never_targets_live_database():
    args = backup.restore_query_args("solar-restore-verify-123")
    assert "solar_prices" not in " ".join(args)
    assert "--dbname=solar_restore" in args
    assert "gold.current_panel_ranking" in args[-1]


def test_verification_rejects_tampered_dump_without_running_docker(tmp_path, monkeypatch):
    dump = prepare_valid_dump(tmp_path)
    dump.write_bytes(b"bad")
    monkeypatch.setattr(backup, "docker", lambda *args, **kwargs: pytest.fail("Docker must not run"))
    with pytest.raises(backup.BackupError):
        backup.verify_backup(dump)


def test_backup_creates_manifest_and_never_writes_db(tmp_path, monkeypatch):
    commands = []

    def fake_docker(*args, **kwargs):
        commands.append(args)
        if args[:2] == ("inspect", "-f"):
            return proc(out="true\n")
        if args[:3] == ("exec", "solar-postgres", "printenv"):
            return proc(out={"POSTGRES_DB": "solar_prices\n", "POSTGRES_USER": "postgres\n"}[args[-1]])
        if args[0] == "cp":
            Path(args[-1]).write_bytes(b"pg_dump custom bytes")
        return proc()

    monkeypatch.setattr(backup, "docker", fake_docker)
    dump = backup.create_backup(tmp_path)
    assert dump.exists()
    assert backup.validate_manifest(dump)["database"] == "solar_prices"
    assert any(c[0:3] == ("exec", "solar-postgres", "pg_dump") for c in commands)
    assert any(c[0:3] == ("exec", "solar-postgres", "rm") for c in commands)
    assert all("pg_restore" not in c or "--list" in c for c in commands)
    assert not list(tmp_path.glob("*.partial"))


def test_verify_restores_disposable_database_and_cleans_up(tmp_path, monkeypatch):
    dump = prepare_valid_dump(tmp_path)
    commands = []

    def fake_docker(*args, **kwargs):
        commands.append(args)
        if args[:2] == ("container", "inspect"):
            return proc(out="exists\n")
        if args[0] == "exec" and "psql" in args:
            return proc(out=json.dumps({"scrape_runs": 2, "raw_panels": 6, "silver_panels": 6,
                                        "gold_ranking": 3, "gold_history": 6, "gold_daily": 2}) + "\n")
        return proc()

    monkeypatch.setattr(backup, "docker", fake_docker)
    report = backup.verify_backup(dump, wait_seconds=1)
    assert report["result"] == "PASS"
    assert report["restored_counts"]["gold_ranking"] == 3
    assert any(cmd[0] == "rm" and "-f" in cmd for cmd in commands)
    assert any(cmd[:2] == ("volume", "rm") for cmd in commands)
    assert all("solar-postgres" not in " ".join(cmd) for cmd in commands)
    assert dump.with_name(dump.name + ".verified.json").exists()


def test_restore_failure_cleans_temp_resources(tmp_path, monkeypatch):
    dump = prepare_valid_dump(tmp_path)
    commands = []

    def fake_docker(*args, **kwargs):
        commands.append(args)
        if args[:2] == ("container", "inspect"):
            return proc(out="exists\n")
        if args[0] == "exec" and "pg_restore" in args:
            raise backup.BackupError("Restore failed")
        return proc()

    monkeypatch.setattr(backup, "docker", fake_docker)
    with pytest.raises(backup.BackupError, match="Restore failed"):
        backup.verify_backup(dump, wait_seconds=1)
    assert any(cmd[0] == "rm" for cmd in commands)
    assert any(cmd[:2] == ("volume", "rm") for cmd in commands)
