"""Backup automation safety tests. Never run Docker or access the real database."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from scripts import backup_automation as a


def make_verified(directory: Path, stamp: datetime, suffix: str = "abcd1234", body: bytes = b"custom-pg-dump") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    dump = directory / f"solar_prices_{stamp:%Y%m%d_%H%M%S}Z_{suffix}.dump"
    dump.write_bytes(body)
    sha = hashlib.sha256(body).hexdigest()
    meta = {"format": "pg_dump-custom", "sha256": sha, "size_bytes": len(body),
            "created_utc": stamp.isoformat(), "database": "solar_prices"}
    a.manifest_path(dump).write_text(json.dumps(meta), encoding="utf-8")
    a.verified_report_path(dump).write_text(json.dumps({
        "result": "PASS", "sha256": sha, "backup_file": dump.name,
        "restored_counts": {"scrape_runs": 2, "raw_panels": 3, "gold_ranking": 2},
    }), encoding="utf-8")
    return dump


def test_verified_backup_accepts_receipt_and_checksum(tmp_path):
    dump = make_verified(tmp_path, datetime(2026, 11, 15, tzinfo=timezone.utc))
    meta, receipt = a.verified_backup(dump)
    assert meta["sha256"] == receipt["sha256"]


def test_reject_modified_dump(tmp_path):
    dump = make_verified(tmp_path, datetime(2026, 11, 15, tzinfo=timezone.utc))
    dump.write_bytes(b"tampered")
    with pytest.raises((a.BackupError, a.AutomationError)):
        a.verified_backup(dump)


def test_reject_forged_receipt_mismatch(tmp_path):
    dump = make_verified(tmp_path, datetime(2026, 11, 15, tzinfo=timezone.utc))
    a.verified_report_path(dump).write_text('{"result":"PASS","sha256":"bad"}')
    with pytest.raises(a.AutomationError, match="receipt"):
        a.verified_backup(dump)


def test_reject_unverified_dump(tmp_path):
    dump = make_verified(tmp_path, datetime(2026, 11, 15, tzinfo=timezone.utc))
    a.verified_report_path(dump).unlink()
    with pytest.raises(a.AutomationError, match="no verification"):
        a.verified_backup(dump)


def test_reject_empty_restore_metrics(tmp_path):
    dump = make_verified(tmp_path, datetime(2026, 11, 15, tzinfo=timezone.utc))
    receipt = json.loads(a.verified_report_path(dump).read_text())
    receipt["restored_counts"]["raw_panels"] = 0
    a.verified_report_path(dump).write_text(json.dumps(receipt))
    with pytest.raises(a.AutomationError, match="Empty"):
        a.verified_backup(dump)


def test_mirror_creates_three_files_with_identical_checksums(tmp_path):
    primary, secondary = tmp_path / "local", tmp_path / "external"
    secondary.mkdir()
    dump = make_verified(primary, datetime(2026, 11, 15, tzinfo=timezone.utc))
    target = a.mirror_verified(dump, secondary, primary)
    assert target.exists()
    assert a._mirror_is_complete(dump, secondary)
    for source in (dump, a.manifest_path(dump), a.verified_report_path(dump)):
        assert a.sha256_file(source) == a.sha256_file(secondary / source.name)


def test_mirror_refuses_existing_conflicting_dump(tmp_path):
    primary, secondary = tmp_path / "local", tmp_path / "external"
    secondary.mkdir()
    dump = make_verified(primary, datetime(2026, 11, 15, tzinfo=timezone.utc))
    existing = secondary / dump.name
    existing.write_bytes(b"do not overwrite me")
    with pytest.raises(a.AutomationError, match="Conflicting"):
        a.mirror_verified(dump, secondary, primary)
    assert existing.read_bytes() == b"do not overwrite me"


def test_reject_mirror_inside_local_directory(tmp_path):
    primary = tmp_path / "local"
    secondary = primary / "mirrored"
    secondary.mkdir(parents=True)
    with pytest.raises(a.AutomationError, match="separate"):
        a.validate_mirror_dir(secondary, primary)


def test_reject_nonexistent_mirror(tmp_path):
    with pytest.raises(a.AutomationError, match="already exist"):
        a.validate_mirror_dir(tmp_path / "absent", tmp_path / "local")


def test_refuse_retention_without_mirror(tmp_path):
    with pytest.raises(a.AutomationError, match="requires"):
        a.run_automation(tmp_path / "backups", retention_days=90)
    assert not (tmp_path / "backups").exists()


def test_refuse_too_short_retention(tmp_path):
    secondary = tmp_path / "external"
    secondary.mkdir()
    with pytest.raises(a.AutomationError, match=">=30"):
        a.run_automation(tmp_path / "backups", mirror_dir=secondary, retention_days=3)


def test_keep_at_least_four_local_verified_archives(tmp_path):
    local, external = tmp_path / "local", tmp_path / "external"
    external.mkdir()
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    dumps = []
    for i in range(8):
        dump = make_verified(local, now - timedelta(days=i * 15), suffix=f"{i:08x}", body=f"dump{i}".encode())
        a.mirror_verified(dump, external, local)
        dumps.append(dump)
    removed = a.prune_local_verified(local, external, retention_days=30, keep_minimum=4, now=now)
    assert set(removed) == set(dumps[4:])
    assert all(d.exists() for d in dumps[:4])
    assert all(not d.exists() for d in dumps[4:])
    assert all((external / d.name).exists() for d in dumps)


def test_no_prune_if_mirror_corrupted(tmp_path):
    local, external = tmp_path / "local", tmp_path / "external"
    external.mkdir()
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    dumps = []
    for i in range(5):
        dump = make_verified(local, now - timedelta(days=i * 20), suffix=f"{i:08x}", body=f"data{i}".encode())
        a.mirror_verified(dump, external, local)
        dumps.append(dump)
    (external / dumps[4].name).write_bytes(b"corrupted")
    assert a.prune_local_verified(local, external, retention_days=30, now=now) == []
    assert dumps[4].exists()


def test_unverified_archives_remain_untouched(tmp_path):
    local, external = tmp_path / "local", tmp_path / "external"
    external.mkdir()
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    for i in range(4):
        d = make_verified(local, now - timedelta(days=i), suffix=f"{i:08x}")
        a.mirror_verified(d, external, local)
    old = make_verified(local, now - timedelta(days=200), suffix="ffffffff")
    a.verified_report_path(old).unlink()   # no restore verification
    assert a.prune_local_verified(local, external, retention_days=30, now=now) == []
    assert old.exists()


def test_lock_blocks_concurrent_jobs(tmp_path):
    with a.exclusive_run(tmp_path):
        with pytest.raises(a.AutomationError, match="already running"):
            with a.exclusive_run(tmp_path):
                pass
    assert not (tmp_path / ".weekly_backup.lock").exists()


def test_lock_removed_after_exception(tmp_path):
    with pytest.raises(ZeroDivisionError):
        with a.exclusive_run(tmp_path):
            1 / 0
    assert not (tmp_path / ".weekly_backup.lock").exists()


def test_run_stores_success_and_status_without_docker(tmp_path, monkeypatch):
    local = tmp_path / "local"
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)

    def fake_create(directory):
        return make_verified(directory, now)

    def fake_verify(dump):
        return {"result": "PASS", "sha256": a.sha256_file(dump)}

    monkeypatch.setattr(a, "create_backup", fake_create)
    monkeypatch.setattr(a, "verify_backup", fake_verify)
    result = a.run_automation(local)
    assert result["status"] == "PASS"
    assert "mirror_warning" in result
    assert a.status(local)["backup"] == result["backup"]
    assert json.loads((local / "status" / "latest_success.json").read_text())["status"] == "PASS"


def test_failed_verify_preserves_previous_success_and_records_failure(tmp_path, monkeypatch):
    local = tmp_path / "local"
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(a, "create_backup", lambda directory: make_verified(directory, now))
    monkeypatch.setattr(a, "verify_backup", lambda dump: {"result": "PASS", "sha256": a.sha256_file(dump)})
    a.run_automation(local)
    monkeypatch.setattr(a, "verify_backup", lambda dump: (_ for _ in ()).throw(RuntimeError("fail restore")))
    with pytest.raises(RuntimeError):
        a.run_automation(local)
    assert a.status(local)["status"] == "FAIL"
    assert json.loads((local / "status" / "latest_success.json").read_text())["status"] == "PASS"


def test_status_command_offline(tmp_path, capsys):
    status = tmp_path / "status"
    status.mkdir()
    (status / "last_attempt.json").write_text('{"status":"PASS","backup":"test.dump"}')
    assert a.main(["status", "--backup-dir", str(tmp_path)]) == 0
    assert "test.dump" in capsys.readouterr().out


def test_task_installer_uses_logged_on_user_and_python(tmp_path):
    code = (Path(__file__).parents[1] / "scripts" / "register_weekly_backup_task.ps1").read_text()
    assert "New-ScheduledTaskTrigger" in code
    assert "Register-ScheduledTask" in code
    assert "-LogonType Interactive" in code
    assert "backup_automation.py" in code
    assert "-RunLevel Limited" in code
    assert "docker compose down" not in code.lower()


def test_retention_plan_is_non_destructive(tmp_path, capsys):
    local, external = tmp_path / "local", tmp_path / "external"
    external.mkdir()
    now = datetime.now(timezone.utc)
    dumps = []
    for i in range(5):
        dump = make_verified(local, now - timedelta(days=i * 30), suffix=f"{i:08x}", body=f"data{i}".encode())
        a.mirror_verified(dump, external, local)
        dumps.append(dump)
    assert a.main(["plan", "--backup-dir", str(local), "--mirror-dir", str(external),
                   "--retention-days", "60"]) == 0
    assert "dry_run" in capsys.readouterr().out
    assert all(dump.exists() for dump in dumps)
