import pandas as pd
import pytest

from dashboard.insights import price_drop_events, latest_prices_for_comparison


def fixtures():
    history = pd.DataFrame([
        # One product decreases once (20%) and recovers partially (not a drop).
        {"source_url": "a", "scrape_id": 1, "title": "Panel A", "observed_at": "2026-10-01", "price_pln": 100.0, "power_w": 500, "pln_per_watt": .2},
        {"source_url": "a", "scrape_id": 2, "title": "Panel A", "observed_at": "2026-10-02", "price_pln": 80.0, "power_w": 500, "pln_per_watt": .16},
        {"source_url": "a", "scrape_id": 3, "title": "Panel A", "observed_at": "2026-10-03", "price_pln": 90.0, "power_w": 500, "pln_per_watt": .18},
        # A second product has two separate discount events.
        {"source_url": "b", "scrape_id": 4, "title": "Panel B", "observed_at": "2026-10-01", "price_pln": 500.0, "power_w": 600, "pln_per_watt": .83},
        {"source_url": "b", "scrape_id": 5, "title": "Panel B", "observed_at": "2026-10-02", "price_pln": 450.0, "power_w": 600, "pln_per_watt": .75},
        {"source_url": "b", "scrape_id": 6, "title": "Panel B", "observed_at": "2026-10-03", "price_pln": 400.0, "power_w": 600, "pln_per_watt": .67},
        # Removed from current catalog but did decrease historically.
        {"source_url": "old", "scrape_id": 7, "title": "Old", "observed_at": "2026-10-01", "price_pln": 400.0, "power_w": 400, "pln_per_watt": 1.0},
        {"source_url": "old", "scrape_id": 8, "title": "Old", "observed_at": "2026-10-03", "price_pln": 100.0, "power_w": 400, "pln_per_watt": .25},
    ])
    ranking = pd.DataFrame([
        {"source_url": "a", "is_available": True, "overall_rank": 1},
        {"source_url": "b", "is_available": False, "overall_rank": 2},
    ])
    return history, ranking


def test_drop_detection_uses_consecutive_observations():
    h, r = fixtures()
    drops = price_drop_events(h, r, available_only=False)
    assert set(drops["source_url"]) == {"a", "b"}
    assert len(drops) == 3
    a = drops[drops.source_url.eq("a")].iloc[0]
    assert a["drop_pln"] == 20
    assert a["drop_pct"] == 20
    assert a["previous_price_pln"] == 100


def test_optional_current_availability_and_historical_filters():
    h, r = fixtures()
    assert price_drop_events(h, r)["source_url"].tolist() == ["a"]
    assert set(price_drop_events(h, r, current_only=False, available_only=False)["source_url"]) == {"a", "b", "old"}
    assert set(price_drop_events(h, r, current_only=True, available_only=False)["source_url"]) == {"a", "b"}


def test_window_and_minimum_threshold():
    h, r = fixtures()
    # from last DB observation (Oct 3), 1-day window covers Oct 2 and Oct 3
    assert len(price_drop_events(h, r, days=1, min_drop_pct=19, current_only=False, available_only=False)) == 2
    assert price_drop_events(h, r, days=30, min_drop_pct=80, current_only=False, available_only=False).empty


def test_no_history_and_invalid_input():
    h, r = fixtures()
    assert price_drop_events(h.iloc[0:0], r).empty
    with pytest.raises(ValueError):
        price_drop_events(h, r, days=0)


def test_comparison_keeps_original_rank():
    _, r = fixtures()
    assert latest_prices_for_comparison(r, ["b", "a"])["source_url"].tolist() == ["a", "b"]
