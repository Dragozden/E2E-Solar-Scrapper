# PV Market Analytics — Streamlit v3

Interactive, read-only dashboard for the E2E Solar Scraper project.

## Sources

- `gold.current_panel_ranking`: the latest completed `SUCCESS` scrape (latest catalog snapshot)
- `gold.product_price_history`: historical observations (one per product URL and scrape run)
- `gold.daily_market_prices`: available-product aggregates for **observed** dates
- `bronze.scrape_runs` + `bronze.panel_scrape_raw`: optional monitoring tab (read-only)

## Features

1. **Overview** — KPIs, market trends, power-vs-price scatter, top available offers.
2. **Ranking** — filters by name, availability, power and PLN/W; links and CSV export.
3. **Price drops** — historical *consecutive measurement* declines for the same URL. Choose lookback, minimum percentage, and whether to include retired/unavailable products. A 'drop' is not necessarily a store promotion.
4. **Comparison** — compare up to five currently listed products by price or price/W, with optional latest measurement per day and a snapshot parameter table.
5. **Product history** — individual price and PLN/W plots and all observations.
6. **Market trends** — daily means and offer counts, on actual measured dates only.
7. **Data quality** — count agreement, missing URLs, duplicate URL detection, and **separate** volume-drop warning. Up to 80 recent scrape runs.

## Installation

From the repository root on Windows PowerShell:

```powershell
uv add streamlit plotly
uv run python -m pytest -q
uv run python -m streamlit run dashboard/app.py
```

The app reads `.env` in the repository root (`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`). Ensure the database is reachable and the three dbt Gold models exist. The data-quality tab additionally requires SELECT access to the two Bronze tables. It degrades independently if the extra read is not permitted.

The read-only connection option prevents SQL changes during each connection. For deployments, also configure an actual PostgreSQL user with **SELECT-only** permissions (not the administrative `postgres` user).

## Definitions / limitations

- Product identity is the retailer's `source_url` (different URL means a different product for this MVP).
- A price drop is `previous price - new price > 0` between two adjacent successful **observations**, not between market averages or between all-time highs and lows. Events can include several cuts for one product.
- The lookback window anchors to the latest recorded `observed_at` in Gold. This makes the analysis meaningful for historic datasets when Airflow is paused.
- 'Present in latest snapshot' and 'available now' are based on the latest recorded scrape, not a real-time store lookup.
- The comparison chart does not interpolate missing measurements; it only plots observed points (line segments visually connect measurements).
- Daily market averages reflect the changing available catalog, **not** a constant basket of identical products.
- Bronze quality checks treat `SUCCESS` with zero records, count mismatch, missing URL or duplicates as **FAIL**. A large catalog shrink is a **warning**, not an automatic failure. Older failed scrape runs remain visible as `FAILED`.
- Price tax (gross/net) has not been independently verified.
- Cache is 300 seconds; click `Odśwież dane` to invalidate both Gold and Bronze caches.

## Code layout

- `app.py`: Streamlit widgets and views
- `analytics.py`: ranking filters and individual-product summaries
- `insights.py`: consecutive-observation price drops and comparison table
- `monitoring.py`: independent run-integrity and volume-anomaly classification
- `charts.py`: Plotly figures using real observation dates
- `db.py`: read-only SQL access and field conversions
- `tests/test_dashboard_*.py`: unit tests on synthetic fixtures

## Suggested next steps

- Add a *full latest-snapshot* time-series model if daily counts must reflect an entire final run, rather than the union of products observed that day.
- Consider comparing a fixed cohort across days to reduce catalog-composition effects.
- Add an Airflow alert task or notification separate from the dashboard UI; the monitoring tab itself does not send alerts.
- Add a Streamlit service to Docker Compose with a dedicated read-only database role.
