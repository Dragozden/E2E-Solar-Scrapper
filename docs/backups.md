# PostgreSQL backup & isolated restore — E2E Solar

_Stage 9.2. Windows PowerShell + Docker Desktop. Applies to the existing PostgreSQL 17 container named `solar-postgres`._

## Scope and safety

- `scripts/postgres_backup.py create` runs **read-only `pg_dump`** against the existing `solar_prices` database. It does not reset tables or alter the running DAG.
- It creates a compressed, logical PostgreSQL archive (`.dump`) in the local `backups/` directory, with a SHA-256 manifest (`.dump.json`). `backups/` is excluded from Git and Docker build contexts.
- `verify` uses a newly generated Docker container **on the `none` network** with a separate disposable Docker volume. It restores the dump there, queries Bronze/Silver/Gold, records a verification report, and attempts to delete only its own temporary container and volume.
- No `docker compose down`, no deletion of `postgres_data`, and no restore into `solar-postgres` are part of the workflow.
- This backup covers the **PostgreSQL database**: Bronze data and Silver/Gold definitions. It does **not** cover Airflow's SQLite metadata and history, its logs, pgAdmin configuration, local `.env` secrets, or Git source. Those need their own recovery plan.

## Before starting

1. Confirm Docker Desktop is running and `solar-postgres` is healthy:

   ```powershell
   cd "E:\Repos Projects\E2E Solar Scrapper\docker"
   docker compose ps
   cd ..
   ```

2. Make sure sufficient disk space is available on the Docker engine and on the backup destination. Backups contain historical data. A logical dump is a transactionally consistent PostgreSQL snapshot, but restore verification still has to run to prove it can be read and restored.

3. Do not run schema migrations during the backup if you can avoid it. Running the normal scraper is typically acceptable, but planned DB changes should be coordinated.

## Step 1: Create a local backup

From the **repository root**:

```powershell
uv run --frozen python scripts/postgres_backup.py create
```

A successful backup produces a pair such as:

```text
backups/
  solar_prices_20261115_180000Z_abcd1234.dump
  solar_prices_20261115_180000Z_abcd1234.dump.json
```

The manifest records file size, creation timestamp, database name and SHA-256. It **does not** contain credentials. The backup itself contains data and should be treated as confidential.

To choose another destination (for example, an encrypted external drive):

```powershell
uv run --frozen python scripts/postgres_backup.py create --directory "F:\SecureSolarBackups"
```

Do **not** redirect binary `pg_dump` output through `>` in Windows PowerShell 5.1. This script writes the dump inside the container, then transfers it using `docker cp` as bytes.

## Step 2: Verify restore in an isolated instance

The command below selects the most recent `.dump` under `backups/`:

```powershell
uv run --frozen python scripts/postgres_backup.py verify
```

Or explicitly choose one backup:

```powershell
uv run --frozen python scripts/postgres_backup.py verify "backups\solar_prices_20261115_180000Z_abcd1234.dump"
```

Successful verification produces a third file:

```text
backups/solar_prices_20261115_180000Z_abcd1234.dump.verified.json
```

The verification report records `PASS` and restored row counts for:

- `bronze.scrape_runs` and `bronze.panel_scrape_raw`;
- `silver.stg_panels`;
- `gold.current_panel_ranking`, `gold.product_price_history`, and `gold.daily_market_prices`.

The verification expects nonempty scraping history and a nonempty Gold ranking. A genuinely empty development database will fail this business-data check; this is intentional for the current project.

**What happens during verification:** a temporary `postgres:17` container is started with no published ports and no network connection, the dump is copied in, `pg_restore --single-transaction --exit-on-error` restores the objects, then SQL checks run. Finally, the script removes the unique temporary container and volume. If cleanup fails, it prints their generated names so you can inspect them without touching `postgres_data`.

## Step 3: Confirm your original environment is untouched

```powershell
cd "E:\Repos Projects\E2E Solar Scrapper\docker"
docker compose ps
cd ..
```

`solar-postgres`, `solar-airflow`, `solar-dashboard` and `solar-pgadmin` should still be present, as before. Verification itself never alters the original PostgreSQL database.

## Backup strategy and recovery limitations

For a home-hosted portfolio deployment, a reasonable first policy is **one backup after meaningful schema changes and one scheduled weekly backup**, with a periodic restore drill. Set retention according to disk space and privacy requirements. This package intentionally never deletes old backups automatically.

Move verified backups and manifests to a separate, **encrypted** storage location; a copy only on the same PC/drive is not protection from disk loss. Use BitLocker-encrypted media or another protected backup mechanism. SHA-256 detects accidental corruption or modification but does **not** encrypt or authenticate the file against an active adversary. If stronger tamper resistance is needed, sign the manifest or use a trusted immutable backup store.

Full recovery would also need your repository, a compatible `postgres:17` image, the `.env` configuration (stored separately), and, if required, Airflow metadata/configuration. Never share real dump files in issues, CI artifacts, or a public repository.

## Troubleshooting

- `Docker CLI nie jest dostepny`: install/open Docker Desktop and retry.
- `password authentication failed` or `peer authentication failed`: database local-socket authentication differs from the stock Compose setup; inspect `pg_hba.conf` or use the appropriate authorized account. Do not print database passwords in CI or chat.
- `Checksum SHA256`: the dump differs from its manifest; do not restore it until investigated.
- `pg_restore` error: check the PostgreSQL image major version and error details. The tool intentionally uses version 17 to match this project.
- `WARN: usun ... wolumen`: cleanup was incomplete. Remove **only** the temporary name printed by the script, never `postgres_data` or the full Compose stack.

## Tests

The backup and audit unit tests use mocked Docker commands, so CI runs them without access to production data:

```powershell
uv run --frozen python -m pytest tests/test_postgres_backup.py tests/test_security_audit.py -q
```

The tests verify command construction, checksum validation, failure handling, and temporary-resource cleanup. A **real** restore drill must still be performed on your machine before declaring the backup recovery procedure tested end-to-end.
