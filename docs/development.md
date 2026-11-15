# Development & runbook — E2E Solar

_Updated: 15 November 2026. Applies to Windows PowerShell, Docker Compose, uv and the local environment._

## Services and entry points

| Component | Path | Purpose |
|---|---|---|
| Scraper | `scraper/` | Playwright extraction, parsing, Bronze loading |
| DAGs | `airflow/dags/` | Pipeline and daily quality watchdog |
| dbt | `dbt/solar_dbt/` | Silver/Gold models and tests |
| Dashboard | `dashboard/` | Streamlit/Plotly read-only UI |
| Compose | `docker/docker-compose.yml` and `.override.yml` | DB, pgAdmin, Airflow, Streamlit |
| CI | `.github/workflows/ci.yml` | Python tests, dbt integration, Docker builds |

## Full setup from a clean clone

1. Install Git, Docker Desktop (Compose), and `uv`.
2. Clone the repository; from the repository root run `uv sync --frozen`.
3. Create a local root `.env` using `.env.example` and configure PostgreSQL credentials. They must match the actual database state. Do not commit credentials.
4. Start **only** the base database services:

   ```powershell
   docker compose -f docker/docker-compose.yml up -d postgres pgadmin
   ```

5. Initialize a real sample from the shop (this **does** contact the retailer and write to Bronze), then run dbt:

   ```powershell
   uv run --frozen python -m playwright install chromium
   uv run --frozen python -m scraper.main
   uvx --env-file .env --python 3.13 --from 'dbt-postgres==1.11.0' dbt build --project-dir dbt/solar_dbt --profiles-dir dbt/solar_dbt
   ```

6. Create/select the dashboard's read-only database credentials **after Gold views exist**:

   ```powershell
   uv run --frozen python scripts/setup_dashboard_reader.py
   ```

7. Start all four services:

   ```powershell
   cd docker
   docker compose up -d --build
   docker compose ps
   cd ..
   ```

   Open Streamlit `http://localhost:8501`, Airflow `http://localhost:8080`, and pgAdmin `http://localhost:5050`.

8. Run the local test suite:

   ```powershell
   uv run --frozen python -m pytest -q
   ```

   The scraper regression fixture tests use local HTML and can be run without the live retailer:

   ```powershell
   uv run --frozen python -m pytest tests/test_extractor_regression.py -q
   ```

   If you are on a fresh clone, ensure Chromium has been installed first.

## Common Docker commands

Run from `docker/` so that the Compose override is loaded automatically:

```powershell
cd docker
docker compose config --services
docker compose ps
docker compose logs --tail 100 airflow
docker compose logs --tail 100 dashboard
docker compose exec airflow airflow dags list
```

Expected services: `postgres`, `pgadmin`, `airflow`, `dashboard`. `solar_data_watchdog` and `solar_el_pipeline` are two Airflow **DAGs**, not separate containers. Airflow discovers files via a bind mount; changes to dependencies or Dockerfiles require a rebuild, while Python files mounted from the host ordinarily do not.

**Never use `docker compose down -v` during routine maintenance.** It deletes named volumes, which can hold PostgreSQL history and Airflow state.

## Running the pipeline

- Main DAG: `solar_el_pipeline`, daily **00:02 Europe/Warsaw**; tasks `scrape_to_bronze` → `build_dbt_models` → `validate_pipeline`.
- Watchdog DAG: `solar_data_watchdog`, daily **09:00 Europe/Warsaw**; default freshness threshold **30 hours**.
- On-demand run: trigger the **entire** main DAG in the Airflow UI rather than only re-running dbt after changing the scraper.
- A successful CI build does not imply that the local Airflow scheduler is running.

## Where to investigate failures

| Area | Location / command |
|---|---|
| Airflow tasks | Airflow UI task instance logs or `/opt/airflow/logs/` in the container |
| dbt log | `/opt/airflow/solar/dbt/logs/dbt.log` |
| dbt result metadata | `/opt/airflow/solar/dbt/target/run_results.json` |
| Runtime status | `docker compose ps` and `docker compose logs --tail 100 airflow` |
| Scraper watchdog | `docker compose exec airflow /opt/airflow/solar-venv/bin/python -m scraper.watchdog` |
| CI | GitHub Actions → CI — E2E Solar |

`dbt/target` and `dbt/logs` are generated artifacts and can be replaced by subsequent builds. The Bronze run history is the persistent source of ingestion metadata.

A latest-run integrity FAIL checks (among others): `actual_count > 0`, expected and actual counts match, URLs are present, and URLs are unique within that run. A product count decrease alone is a **warning**; it does not prove that products were removed from the retailer.

## Alerts and freshness

See [alerting.md](alerting.md) for optional Discord/Slack webhook configuration and safe test commands. The `SOLAR_ALERT_WEBHOOK_URL` value is a secret and belongs only in the local root `.env`. If the `.env` changes, re-create the Airflow container to load updated environment values. Watchdog alerts are ineffective while Airflow or the host computer are stopped.

## Data preservation and credentials

- PostgreSQL initialization SQL in `docker/postgres/init/` is applied to an **empty** data volume, not automatically re-run as schema migrations.
- `POSTGRES_PASSWORD` in Compose does **not** rotate the password of an existing PostgreSQL cluster by itself.
- Current Compose credentials are **development defaults**, not appropriate for an internet-facing deployment. Treat `dashboard/.env` as a secret.
- Keep `.env`, `dashboard/.env`, dbt target artifacts and all database dumps out of Git. Check `git status` before committing.
- Implement and test a **backup/restore** process before migrating the system to another machine or publishing it.

## Release verification

Use [release_checklist.md](release_checklist.md) to test fresh-clone reproducibility, secrets, backups, and presentation artifacts. A green CI indicates that tested code paths pass on GitHub; it is not equivalent to a production-ready deployment.
