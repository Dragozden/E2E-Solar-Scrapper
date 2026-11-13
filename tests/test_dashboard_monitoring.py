import pandas as pd
import pytest
from dashboard.monitoring import evaluate_runs


def runs_example():
    return pd.DataFrame([
        {"scrape_run_id": "r1", "started_at": "2026-10-27", "finished_at": "2026-10-27 01:00", "status": "SUCCESS", "expected_count": 288, "actual_count": 288, "missing_urls": 0, "duplicate_urls": 0},
        {"scrape_run_id": "r2", "started_at": "2026-10-28", "finished_at": "2026-10-28 01:00", "status": "SUCCESS", "expected_count": 126, "actual_count": 126, "missing_urls": 0, "duplicate_urls": 48},
        {"scrape_run_id": "r3", "started_at": "2026-10-29", "finished_at": "2026-10-29 01:00", "status": "FAILED", "expected_count": None, "actual_count": 0, "missing_urls": 0, "duplicate_urls": 0},
        {"scrape_run_id": "r4", "started_at": "2026-10-30", "finished_at": "2026-10-30 01:00", "status": "SUCCESS", "expected_count": 78, "actual_count": 78, "missing_urls": 0, "duplicate_urls": 0},
        {"scrape_run_id": "r5", "started_at": "2026-10-31", "finished_at": "2026-10-31 01:00", "status": "SUCCESS", "expected_count": 72, "actual_count": 72, "missing_urls": 0, "duplicate_urls": 0},
    ])


def test_monitor_classifies_integrity_and_volume_independently():
    runs = evaluate_runs(runs_example())
    states = runs.set_index("scrape_run_id")
    assert states.loc["r1", "quality_status"] == "PASS"
    assert states.loc["r2", "quality_status"] == "FAIL"  # 48 repeated URLs
    assert states.loc["r4", "quality_status"] == "PASS"
    assert states.loc["r3", "quality_status"] == "FAILED"
    assert bool(states.loc["r2", "volume_warning"])
    assert not bool(states.loc["r4", "volume_warning"])
    assert abs(float(states.loc["r2", "drop_pct_vs_previous_success"]) - (210 / 288 * 100)) < 1e-6


def test_quality_detects_missing_url_and_missing_count():
    df = runs_example()
    df.loc[df.scrape_run_id.eq("r4"), "missing_urls"] = 1
    df.loc[df.scrape_run_id.eq("r5"), "expected_count"] = None
    states = evaluate_runs(df).set_index("scrape_run_id")
    assert states.loc["r4", "quality_status"] == "FAIL"
    assert states.loc["r5", "quality_status"] == "FAIL"


def test_empty_runs_and_threshold_validation():
    assert evaluate_runs(runs_example().iloc[:0]).empty
    with pytest.raises(ValueError):
        evaluate_runs(runs_example(), drop_warning_pct=110)
