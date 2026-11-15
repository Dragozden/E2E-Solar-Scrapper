"""Read-only acceptance checks are pure or fully mocked in CI."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import local_release_check as local


def fake_process(stdout="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


def test_postgres_requires_health():
    assert local.classify_container_state("solar-postgres", {"Status": "running", "Health": {"Status": "healthy"}}).status == "PASS"
    assert local.classify_container_state("solar-postgres", {"Status": "running"}).status == "WARN"


def test_unhealthy_and_stopped_containers_fail():
    assert local.classify_container_state("solar-dashboard", {"Status": "running", "Health": {"Status": "unhealthy"}}).status == "FAIL"
    assert local.classify_container_state("solar-airflow", {"Status": "exited"}).status == "FAIL"


def test_starting_container_warns():
    assert local.classify_container_state("solar-dashboard", {"Status": "running", "Health": {"Status": "starting"}}).status == "WARN"


def test_inspection_failure_is_reported_without_crashing(monkeypatch):
    monkeypatch.setattr(local, "run_command", lambda args, **kwargs: fake_process(returncode=1))
    checks = local.inspect_containers()
    assert len(checks) == 4
    assert all(check.status == "FAIL" for check in checks)


def test_dag_check_requires_both_names(monkeypatch):
    monkeypatch.setattr(local, "run_command", lambda args, **kwargs: fake_process("solar_el_pipeline\nsolar_data_watchdog\n"))
    assert local.check_airflow_dags().status == "PASS"
    monkeypatch.setattr(local, "run_command", lambda args, **kwargs: fake_process("solar_el_pipeline\n"))
    assert local.check_airflow_dags().status == "FAIL"


def test_reader_is_check_only(monkeypatch):
    recorded = []
    def runner(args, **kwargs):
        recorded.append(args)
        return fake_process("READER PASS — read-only")
    monkeypatch.setattr(local, "run_command", runner)
    assert local.check_reader_permissions().status == "PASS"
    assert recorded[0][-1] == "--check"


def test_reader_rejects_nonzero_exit(monkeypatch):
    monkeypatch.setattr(local, "run_command", lambda args, **kwargs: fake_process("", 1))
    assert local.check_reader_permissions().status == "FAIL"


def test_watchdog_is_read_only_command(monkeypatch):
    recorded = []
    def runner(args, **kwargs):
        recorded.append(args)
        return fake_process("WATCHDOG PASS: latest Bronze SUCCESS age=1.0h")
    monkeypatch.setattr(local, "run_command", runner)
    assert local.check_watchdog().status == "PASS"
    assert recorded[0][-2:] == ["-m", "scraper.watchdog"]


def test_recent_pass_backup():
    now = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)
    report = {"status": "PASS", "completed_utc": (now - timedelta(hours=3)).isoformat(), "backup": "test.dump"}
    assert local.backup_recency_check(report, now=now, max_age_days=8).status == "PASS"


def test_old_backup_fails():
    now = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)
    report = {"status": "PASS", "completed_utc": (now - timedelta(days=9)).isoformat(), "backup": "test.dump"}
    assert local.backup_recency_check(report, now=now, max_age_days=8).status == "FAIL"


def test_failed_attempt_fails_even_if_backup_name_exists():
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    report = {"status": "FAIL", "backup": "previous.dump"}
    assert local.backup_recency_check(report, now=now, max_age_days=8).status == "FAIL"


def test_naive_or_future_dates_fail():
    now = datetime(2026, 11, 15, 20, tzinfo=timezone.utc)
    assert local.backup_recency_check({"status":"PASS", "backup":"x", "completed_utc":"2026-11-15T20:00:00"}, now=now, max_age_days=8).status == "FAIL"
    assert local.backup_recency_check({"status":"PASS", "backup":"x", "completed_utc":"2026-11-16T20:00:00+00:00"}, now=now, max_age_days=8).status == "FAIL"


def test_backup_without_status_is_fail(tmp_path):
    assert local.check_backup(tmp_path, None)[0].status == "FAIL"


def test_backup_and_mirror_pass(monkeypatch, tmp_path):
    backup_dir = tmp_path / "backups"
    (backup_dir / "status").mkdir(parents=True)
    mirror = tmp_path / "usb"
    mirror.mkdir()
    dump = backup_dir / "example.dump"
    dump.write_bytes(b"fake")
    report = {
        "status": "PASS", "backup": dump.name, "sha256": "validhash",
        "completed_utc": datetime.now(timezone.utc).isoformat(),
    }
    (backup_dir / "status" / "last_attempt.json").write_text(json.dumps(report))
    monkeypatch.setattr(local, "verified_backup", lambda p: ({"sha256":"validhash"}, {"result":"PASS"}))
    monkeypatch.setattr(local, "_mirror_is_complete", lambda p, m: True)
    statuses = [check.status for check in local.check_backup(backup_dir, mirror)]
    assert statuses == ["PASS", "PASS"]


def test_backup_without_mirror_warns(monkeypatch, tmp_path):
    backup_dir = tmp_path
    (backup_dir / "status").mkdir()
    report = {"status":"PASS", "backup":"x.dump", "sha256":"a", "completed_utc":datetime.now(timezone.utc).isoformat()}
    (backup_dir / "status" / "last_attempt.json").write_text(json.dumps(report))
    monkeypatch.setattr(local, "verified_backup", lambda p: ({"sha256":"a"}, {"result":"PASS"}))
    assert [v.status for v in local.check_backup(backup_dir, None)] == ["PASS", "WARN"]


def test_bad_mirror_fails(monkeypatch, tmp_path):
    backup_dir = tmp_path / "local"
    backup_dir.mkdir()
    (backup_dir / "status").mkdir()
    mirror = tmp_path / "usb"
    mirror.mkdir()
    report = {"status":"PASS", "backup":"x.dump", "sha256":"a", "completed_utc":datetime.now(timezone.utc).isoformat()}
    (backup_dir / "status" / "last_attempt.json").write_text(json.dumps(report))
    monkeypatch.setattr(local, "verified_backup", lambda p: ({"sha256":"a"}, {"result":"PASS"}))
    monkeypatch.setattr(local, "_mirror_is_complete", lambda p, m: False)
    assert [v.status for v in local.check_backup(backup_dir, mirror)] == ["PASS", "FAIL"]


def test_main_exit_code_without_live_checks(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(local, "all_checks", lambda *args, **kwargs: [local.Check("unit", "PASS", "ok"), local.Check("backup", "WARN", "no mirror")])
    assert local.main(["--backup-dir", str(tmp_path)]) == 0
    assert "1 PASS, 1 WARN, 0 FAIL" in capsys.readouterr().out
    monkeypatch.setattr(local, "all_checks", lambda *args, **kwargs: [local.Check("x", "FAIL", "bad")])
    assert local.main(["--backup-dir", str(tmp_path)]) == 1


def test_missing_usb_on_scheduled_run_records_failure(tmp_path):
    from scripts import backup_automation as automation
    local_path = tmp_path / "backup"
    missing_usb = tmp_path / "F_missing"
    with pytest.raises(automation.AutomationError, match="already exist"):
        automation.run_automation(local_path, mirror_dir=missing_usb)
    assert automation.status(local_path)["status"] == "FAIL"
