# Release checklist — E2E Solar

_Use this checklist before asking someone to clone the project or before hosting a demo._

## Ready to show on GitHub

- [ ] `README.md` accurately describes the current features (Streamlit v3, two DAGs, three CI jobs).
- [ ] Dashboard screenshots appear correctly and contain no credentials or private endpoints.
- [ ] `git status` is clean; `.env`, `dashboard/.env`, webhook URLs, and database dumps are **not tracked**.
- [ ] A full GitHub Actions run passes on the intended release commit.
- [ ] Data assumptions are documented (title-based watts, unknown tax treatment, changing product catalog).

## Reproducibility on a clean machine

- [ ] Fresh `git clone` + `uv sync --frozen` works.
- [ ] Base database Compose starts successfully.
- [ ] Bronze can be populated (live store subject to change) and `dbt build` succeeds.
- [ ] The reader role setup succeeds **after** Gold models exist.
- [ ] All four Compose services start, with dashboard and Airflow accessible on localhost.
- [ ] `pytest` passes offline; GitHub Actions tests do not require the retailer.
- [ ] The user can locate task logs, dbt logs, watchdog output, and failed-run status.

## Before any public demo (not yet satisfied)

- [ ] Replace the development PostgreSQL and pgAdmin passwords; validate credentials against the **existing** database cluster.
- [ ] Remove or secure any authentication-free internet access to Streamlit, Airflow and pgAdmin.
- [ ] Use a dedicated hosted environment, not a port forward from the home workstation.
- [ ] Restrict DB roles, host network access, and webhook secrets.
- [ ] Create a PostgreSQL backup **and prove restore on a separate disposable database/volume**.
- [ ] Add independent uptime monitoring of the service/host and keep data retention under control.
- [ ] Review the retailer's terms and permitted request frequency before hosting scheduled scraping.

## Suggested release acceptance tests

```powershell
# From repository root
uv run --frozen python -m pytest -q
git status

# From docker/ directory
cd docker
docker compose config --quiet
docker compose ps
docker compose exec airflow airflow dags list
```

**Do not run `docker compose down -v` on your working project.** This deletes named volumes and may remove historical observations.
