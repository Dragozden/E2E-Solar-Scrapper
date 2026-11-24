# Stage 9.3 — Local credential bootstrap & rotation

**For Windows PowerShell / Docker Desktop. These commands are LOCAL ONLY.** Do not use these scripts against any production or remote database. The script deliberately supports only the local `postgres` role, `solar_prices` database, and loopback PostgreSQL address.

## A. Rotation of an EXISTING installation (your current project)

1. Make sure both Airflow DAGs have finished. **Pause both DAGs in the Airflow UI during maintenance.** Keep the host running and do not start a new scrape while rotating credentials.
2. Run and verify a fresh backup (even if a previous one exists):

   ```powershell
   cd "E:\Repos Projects\E2E Solar Scrapper"
   uv run --frozen python scripts/postgres_backup.py create
   uv run --frozen python scripts/postgres_backup.py verify
   ```

3. Ensure `docker/docker-compose.yml` has been replaced by the Stage 9.3 version. Before proceeding, inspect the existing root `.env` locally; it must have valid **current** PostgreSQL credentials. The script will preserve other settings, including optional alert webhooks. Backups themselves do **not** include role login passwords, so preserve your old secret in a private password manager until the rotation is verified.
4. Explicitly rotate the local PostgreSQL role and generate distinct PostgreSQL/pgAdmin credentials. **No passwords are printed.** The script changes PostgreSQL's actual role password using an authenticated connection, verifies a new connection, then synchronizes `../.env` and `docker/.env`. It will stop on a missing or outdated verified backup.

   ```powershell
   uv run --frozen python scripts/local_credentials.py rotate --confirm ROTATE_LOCAL_CREDENTIALS
   uv run --frozen python scripts/local_credentials.py check
   ```

5. **Recreate only the affected services** (no `down`, and **never `down -v`**). From `docker/` so Compose reads the newly generated `docker/.env`:

   ```powershell
   cd docker
   docker compose config --quiet
   docker compose up -d --no-deps --force-recreate postgres
   docker compose up -d --no-deps --force-recreate airflow pgadmin
   docker compose ps
   cd ..
   ```

   The dashboard keeps its own `solar_dashboard` SELECT-only login; its `.env` must remain unchanged. **pgAdmin has a separate application login database.** According to pgAdmin's container documentation, `PGADMIN_DEFAULT_PASSWORD` is the password for the *initial* administrator account, not a guaranteed password-rotation mechanism for an already-initialized pgAdmin state. After recreation, attempt to log in using the new password stored privately in `docker/.env`. If that fails but the previous password still works, change the pgAdmin user password manually in the UI and synchronize it with the generated secret; alternatively, export any saved pgAdmin server registrations and deliberately reset only pgAdmin's own disposable storage. **Never reset the PostgreSQL `postgres_data` volume.** No existing pgAdmin state is deleted automatically by this package.

6. Validate without sharing secrets:

   ```powershell
   uv run --frozen python scripts/local_credentials.py check
   uv run --frozen python scripts/security_audit.py --strict
   uv run --frozen python -m pytest -q
   cd docker
   docker compose logs --tail 50 airflow
   docker compose logs --tail 50 dashboard
   docker compose exec airflow /opt/airflow/solar-venv/bin/python -m scraper.watchdog
   cd ..
   ```

   Open localhost:8501, verify pgAdmin and Airflow logins. Reenable your paused Airflow DAGs. For a full ingestion validation, trigger a complete DAG run after maintenance rather than a dbt-only task.

## B. New machine / EMPTY PostgreSQL volume ONLY

For a fresh clone **without existing `.env` files and before database creation**:

```powershell
uv sync --frozen
uv run --frozen python scripts/local_credentials.py init
# Then follow README's steps to start PostgreSQL, scrape, run dbt,
# provision the dashboard reader and launch the full stack.
```

Do **not** run `init` against an existing PostgreSQL volume: a new environment variable does not reset its database password. If `.env` already exists, `init` refuses to overwrite it.

## CI/CD changes

GitHub Actions now creates a disposable `docker/.env` for Compose validation. Real `.env`, `docker/.env` and `dashboard/.env` files must never be committed. Secrets may still be visible to users with privileged access to the Docker daemon, so this remains a **localhost development stack**, not public deployment hardening.

## Recovery precautions

- The script uses best-effort rollback if the SQL change or local file update fails. A power loss cannot make a database update and two filesystem writes truly atomic. If interrupted, **stop; do not re-run blindly**. Inspect the local files and test each known password with a private database client, then reconcile before recreating containers.
- The PostgreSQL dump is a copy of the **database**, not a backup of Docker env secrets or pgAdmin's own configuration.
- Updating `POSTGRES_PASSWORD` in Compose **alone** does not change the existing PostgreSQL role. The rotation command does the actual database change.
- Do not paste `docker compose config` output or the contents of either `.env` into GitHub/issues/chat; Compose may expand secret values.
- No database volumes are deleted or reset by these scripts.
