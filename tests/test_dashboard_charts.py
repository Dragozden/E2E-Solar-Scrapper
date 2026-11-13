"""Plotly chart tests on synthetic data; no database / UI process needed."""

import pandas as pd

from dashboard.charts import price_series, daily_count_chart, top_value_chart


def test_market_bar_chart_has_one_bar_per_observed_day():
    daily = pd.DataFrame({
        "observation_date": [pd.Timestamp("2026-09-16"), pd.Timestamp("2026-10-28")],
        "available_panels": [80, 75],
    })
    fig = daily_count_chart(daily)
    assert fig.data[0].x.tolist() == ["16.09.2026", "28.10.2026"]
    assert len(fig.data[0].y) == 2
    assert fig.layout.xaxis.type == "category"


def test_price_series_does_not_invent_missing_dates():
    data = pd.DataFrame({
        "observed_at": [pd.Timestamp("2026-09-16"), pd.Timestamp("2026-10-28")],
        "price_pln": [343.98, 343.98],
    })
    fig = price_series(data, date_col="observed_at", value_col="price_pln", title="Price", suffix="zł")
    assert len(fig.data) == 1
    assert len(fig.data[0].x) == 2
    assert list(fig.data[0].y) == [343.98, 343.98]
    assert fig.data[0].mode == "lines+markers"


def test_top_ranking_uses_available_only():
    ranking = pd.DataFrame([
        {"title": "Panel fotowoltaiczny A", "pln_per_watt": 0.6, "is_available": False},
        {"title": "Panel fotowoltaiczny B", "pln_per_watt": 0.8, "is_available": True},
        {"title": "Panel fotowoltaiczny C", "pln_per_watt": 0.7, "is_available": True},
    ])
    fig = top_value_chart(ranking)
    assert list(fig.data[0].x) == [0.7, 0.8]
    assert list(fig.data[0].y) == ["C", "B"]


def test_price_power_scatter_uses_only_available_panels():
    from dashboard.charts import price_power_scatter
    ranking = pd.DataFrame([
        {"title": "A", "power_w": 550, "price_pln": 350, "pln_per_watt": 0.6364, "is_available": True},
        {"title": "B", "power_w": 600, "price_pln": 400, "pln_per_watt": 0.6667, "is_available": False},
    ])
    fig = price_power_scatter(ranking)
    assert list(fig.data[0].x) == [550]
    assert list(fig.data[0].y) == [350]


def test_product_comparison_only_selected_and_real_dates():
    from dashboard.charts import product_comparison_chart
    history = pd.DataFrame([
        {"source_url": "a", "scrape_id": 1, "observed_at": "2026-10-01 12:00", "price_pln": 100.0, "pln_per_watt": .2},
        {"source_url": "a", "scrape_id": 2, "observed_at": "2026-10-02 12:00", "price_pln": 90.0, "pln_per_watt": .18},
        {"source_url": "b", "scrape_id": 3, "observed_at": "2026-10-03 12:00", "price_pln": 120.0, "pln_per_watt": .24},
    ])
    fig = product_comparison_chart(history, ["a", "b"], {"a": "Panel a", "b": "Panel b"}, metric="price_pln")
    assert len(fig.data) == 2
    assert sum(len(trace.x) for trace in fig.data) == 3
    assert list(fig.data[0].y) == [100.0, 90.0]


def test_product_comparison_rejects_more_than_five():
    import pytest
    from dashboard.charts import product_comparison_chart
    with pytest.raises(ValueError):
        product_comparison_chart(pd.DataFrame(), ["a", "b", "c", "d", "e", "f"], {})
