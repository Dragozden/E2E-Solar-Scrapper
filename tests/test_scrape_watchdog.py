"""Pure freshness/integrity tests. No PostgreSQL or network required."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from scraper.watchdog import DataHealthError, assert_snapshot_healthy

NOW = datetime(2026, 11, 15, 9, 0, tzinfo=timezone.utc)
RUN_ID = uuid4()


def snapshot(*, age_h=4, expected=72, actual=72, missing=0, duplicates=0, aware=False):
    finished = NOW - timedelta(hours=age_h)
    if not aware:
        finished = finished.replace(tzinfo=None)
    return (RUN_ID, finished, expected, actual, missing, duplicates)


@pytest.mark.parametrize("aware", [False, True])
def test_recent_valid_snapshot_passes(aware):
    age = assert_snapshot_healthy(snapshot(aware=aware), now_utc=NOW)
    assert age == pytest.approx(4)


def test_no_successful_run_is_failure():
    with pytest.raises(DataHealthError, match="No completed SUCCESS"):
        assert_snapshot_healthy(None, now_utc=NOW)


def test_old_snapshot_is_failure():
    with pytest.raises(DataHealthError, match="snapshot is 35.0 h old"):
        assert_snapshot_healthy(snapshot(age_h=35), now_utc=NOW, max_age_hours=30)


@pytest.mark.parametrize("values", [
    dict(expected=73), dict(actual=71), dict(missing=1), dict(duplicates=2),
    dict(expected=0),
])
def test_invalid_integrity_is_failure(values):
    with pytest.raises(DataHealthError, match="invalid Bronze"):
        assert_snapshot_healthy(snapshot(**values), now_utc=NOW)


def test_catalog_drop_is_not_automatically_a_failure():
    assert assert_snapshot_healthy(snapshot(expected=72, actual=72), now_utc=NOW) == pytest.approx(4)


def test_invalid_threshold():
    with pytest.raises(ValueError, match="positive"):
        assert_snapshot_healthy(snapshot(), now_utc=NOW, max_age_hours=0)


def test_future_timestamp_detected():
    with pytest.raises(DataHealthError, match="in the future"):
        assert_snapshot_healthy(snapshot(age_h=-4), now_utc=NOW)


def test_naive_now_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        assert_snapshot_healthy(snapshot(), now_utc=NOW.replace(tzinfo=None))
