"""Quick unit tests; no database, network or Streamlit process required."""

import pandas as pd

from dashboard.analytics import available_metrics, filter_ranking


def sample_ranking():
    return pd.DataFrame([
        {"overall_rank": 1, "title": "JA Solar 550", "power_w": 550, "pln_per_watt": 0.62, "is_available": True},
        {"overall_rank": 2, "title": "TW Solar 450", "power_w": 450, "pln_per_watt": 0.69, "is_available": True},
        {"overall_rank": 3, "title": "JA Solar 400", "power_w": 400, "pln_per_watt": 0.75, "is_available": False},
    ])


def test_filters_availability_power_and_ratio():
    result = filter_ranking(sample_ranking(), availability="Dostępne", min_power=500, max_pln_per_watt=0.7)
    assert result["title"].tolist() == ["JA Solar 550"]


def test_search_treats_regex_as_literal():
    result = filter_ranking(sample_ranking(), search="JA Solar")
    assert len(result) == 2
    assert filter_ranking(sample_ranking(), search=".*").empty


def test_metrics_only_available_products():
    metrics = available_metrics(sample_ranking())
    assert metrics["total"] == 3
    assert metrics["available"] == 2
    assert metrics["min_pln_per_watt"] == 0.62
    assert round(metrics["avg_pln_per_watt"], 4) == 0.655


def test_empty_available_products():
    df = sample_ranking()
    df["is_available"] = False
    assert available_metrics(df)["min_pln_per_watt"] is None


def test_product_summary_first_to_last_price_not_arithmetic_mean():
    from dashboard.analytics import product_history, product_summary
    frame = pd.DataFrame([
        {"source_url": "a", "scrape_id": 2, "observed_at": "2026-10-02", "price_pln": 400},
        {"source_url": "a", "scrape_id": 1, "observed_at": "2026-10-01", "price_pln": 300},
        {"source_url": "a", "scrape_id": 3, "observed_at": "2026-10-03", "price_pln": 350},
        {"source_url": "b", "scrape_id": 4, "observed_at": "2026-10-03", "price_pln": 999},
    ])
    product = product_history(frame, "a")
    result = product_summary(product)
    assert result["observations"] == 3
    assert result["current_price"] == 350
    assert result["first_price"] == 300
    assert result["difference_pln"] == 50
    assert round(result["difference_pct"], 3) == round(50 / 300 * 100, 3)


def test_product_summary_flat_price():
    from dashboard.analytics import product_summary
    product = pd.DataFrame([
        {"price_pln": 343.98}, {"price_pln": 343.98}, {"price_pln": 343.98},
    ])
    result = product_summary(product)
    assert result["difference_pln"] == 0
    assert result["difference_pct"] == 0


def test_latest_observation_per_day_keeps_last_run_only_for_display():
    from dashboard.analytics import latest_observation_per_day
    frame = pd.DataFrame([
        {"scrape_id": 1, "observed_at": "2026-10-28 09:00", "price_pln": 400},
        {"scrape_id": 2, "observed_at": "2026-10-28 21:00", "price_pln": 390},
        {"scrape_id": 3, "observed_at": "2026-10-29 08:00", "price_pln": 380},
    ])
    result = latest_observation_per_day(frame)
    assert result["scrape_id"].tolist() == [2, 3]
    assert len(frame) == 3  # original data is untouched


def test_latest_product_labels_retains_most_recent_name():
    from dashboard.analytics import latest_product_labels
    frame = pd.DataFrame([
        {"scrape_id": 1, "source_url": "url", "observed_at": "2026-10-01", "title": "Old"},
        {"scrape_id": 3, "source_url": "url", "observed_at": "2026-10-02", "title": "New"},
        {"scrape_id": 4, "source_url": None, "observed_at": "2026-10-03", "title": "No URL"},
    ])
    assert latest_product_labels(frame) == {"url": "New"}


def test_invalid_availability_mode_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        filter_ranking(sample_ranking(), availability="undefined")
