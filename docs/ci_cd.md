# Continuous integration — E2E Solar

## What GitHub Actions checks

The workflow `.github/workflows/ci.yml` runs on push to `main`, pull requests targeting `main`, and manual dispatch.

| Job | Purpose | External dependencies |
|---|---|---|
| `python-tests` | Install locked `uv` dependencies, verify tracked dashboard sources, run `pytest`, compile Python | None at runtime (Playwright browser not launched) |
| `dbt-integration` | Start disposable `postgres:17`, initialize Bronze using **the same SQL init scripts as local Docker**, insert two deterministic snapshots, run `dbt build`, verify Silver/Gold result rows and metrics | Ephemeral Postgres container |
| `docker-build` | Validate merged Docker Compose configuration and build dashboard + Airflow images; smoke-test dashboard imports | Docker build network for packages and Playwright |

No production credentials, user data, or local Docker volume are used.

## Data fixture and assertions

`scripts/ci_dbt_integration.py` has two modes:

- `seed`: only on GitHub Actions; creates Bronze schemas and inserts two successful scrape runs with 6 observations, including a real drop from 400.00 PLN to 375.00 PLN.
- `assert`: checks `silver.stg_panels`, `gold.current_panel_ranking`, `gold.product_price_history` and `gold.daily_market_prices`; validates one price drop, latest best price/W ranking and available-panel counts.

The full dbt test suite also runs via `dbt build`. These test observations are not scraped from Soltech and must never be added to the developer database.

## Important: GitHub repo must contain dashboard sources

The GitHub repository checked on 2026-11-13 included `dashboard/Dockerfile` and `dashboard/requirements-docker.txt`, **but not** `dashboard/app.py` and the other dashboard modules. Local Docker can still work because local code exists.

Before committing this workflow, make sure all dashboard Python source and dashboard unit tests are tracked:

```powershell
cd "E:\Repos Projects\E2E Solar Scrapper"
git status --short
git add -A -- dashboard/ tests/
git ls-files -- dashboard/
git status --short
```

`dashboard/.env` must **remain untracked**. Confirm with `git check-ignore -v dashboard/.env` and inspect `git diff --cached --name-only` before committing.

## How to monitor

Go to your GitHub repository → **Actions** → **CI — E2E Solar** and open the newest run. Successful runs show three green jobs. Click a failed job to see the exact command, SQL test, or Docker build step that failed.

Do not interpret a passing CI as proof the external retailer has not changed its HTML. The scraper is deliberately not run against the external site in CI to avoid fragile, network-dependent tests. It should have separate mocked Playwright tests and a scheduled production health monitor.

## Next hardening priorities

- Add parser/extractor tests using stored HTML fixtures and no network.
- Protect `main` with a rule requiring all three checks to pass on pull requests.
- Pin GitHub Actions to immutable commit SHAs and pin image/package versions where appropriate.
- Review database credentials/port exposure and decide on production deployment separately from CI.

## Dependency alignment

The patch also updates `dashboard/requirements-docker.txt` to `plotly>=7.1,<8`, matching the current `pyproject.toml` dependency family. Previously Docker allowed Plotly 6 while Windows installed Plotly 7. Keeping major versions aligned reduces environment-specific visual issues.
