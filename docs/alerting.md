# E2E Solar — automated monitoring and notifications

## Purpose and behavior

Two distinct Airflow DAGs monitor the system:

| DAG | Europe/Warsaw schedule | Behavior |
| --- | --- | --- |
| `solar_el_pipeline` | Daily **00:02** | Playwright → Bronze → dbt → validation; one DAG-level alert after final failure |
| `solar_data_watchdog` | Daily **09:00** | Checks latest completed `SUCCESS` ingestion for age, record counts, URL integrity, and nonempty Gold view |

The watchdog's default threshold is **30 hours**. This is deliberately above the usual daily pipeline period: a normal 00:02 success remains fresh at 09:00, but yesterday's 00:02 snapshot would be approximately 33 hours old. This detection delay assumes the DAG normally completes within hours. Customize `SOLAR_MAX_SNAPSHOT_AGE_HOURS` if needed.

**Important:** the existing `bronze.scrape_runs.finished_at` field is a timezone-naive `TIMESTAMP`, written by the Airflow container using `datetime.now()`. This watchdog interprets that timestamp as UTC because the current container's clock is UTC. If changing the container's `TZ` or migrating to TIMESTAMPTZ, adjust the logic and test it before deploying.

The check does **not** fail merely because the number of retailer products falls versus the previous day. Genuine catalog contractions are warnings in the dashboard, while duplicates, missing URLs, a stale successful run, or an empty Gold ranking are failures.

## Notification setup (optional)

The code supports **Discord** or **Slack incoming webhooks**. Teams Workflows webhooks use a different payload shape and are not supported by this version.

1. Create a private incoming webhook in Discord or Slack.
2. Edit the root `.env` **on your own machine**, never in GitHub, and append (for Discord):

   ```dotenv
   SOLAR_ALERT_FORMAT=discord
   SOLAR_ALERT_WEBHOOK_URL=https://discord.com/api/webhooks/REPLACE_WITH_PRIVATE_VALUE
   SOLAR_MAX_SNAPSHOT_AGE_HOURS=30
   ```

   Use `SOLAR_ALERT_FORMAT=slack` and the corresponding Slack webhook URL if preferred.
3. Apply changed environment to the **Airflow** container (a restart alone does not reload Compose env-file changes):

   ```powershell
   cd "E:\Repos Projects\E2E Solar Scrapper\docker"
   docker compose up -d --no-deps --force-recreate airflow
   ```

4. Send a non-destructive test message (no scraper or database writes):

   ```powershell
   docker compose exec airflow python -c "import sys; sys.path.insert(0, '/opt/airflow/dags'); from solar_alerting import send_alert; print('Sent:', send_alert('E2E Solar - notification test'))"
   ```

   Expected: `Sent: True` plus a test message in your chosen channel. If `False`, the webhook isn't configured in Airflow's environment. Do not share complete webhook URLs in logs or chats.

If `SOLAR_ALERT_WEBHOOK_URL` is unset, DAG failures remain visible in Airflow but no external notification is sent. A delivery failure is logged but never changes the original task/DAG failure.

## Verify DAG registration and health

```powershell
cd "E:\Repos Projects\E2E Solar Scrapper\docker"
docker compose exec airflow airflow dags list
docker compose exec airflow /opt/airflow/solar-venv/bin/python -m scraper.watchdog
docker compose logs --tail 100 airflow
```

For a healthy current snapshot, `scraper.watchdog` prints `WATCHDOG PASS ...`. Running this command does not perform scraping or change any database records.

Airflow DAGs are discovered through the mounted `airflow/dags` directory, so an image rebuild is not needed just for these Python DAG changes. Make sure `solar_data_watchdog` is **unpaused/enabled** in Airflow if it appears paused initially.

## Operational boundaries

- Failure callbacks fire on normal Airflow state transitions, *not* on manual state changes from the UI/CLI.
- Callback delivery failures are documented in **dag processor logs**, not necessarily task logs.
- If Airflow itself is stopped, neither the watcher nor its callbacks can send an alert. External monitoring of the Streamlit HTTP endpoint and/or Airflow service should be configured separately if this needs production reliability.
- The watchdog checks the latest Bronze SUCCESS and that the Gold view returns rows. It cannot independently prove that the latest dbt build completed; the main DAG's failure callback covers dbt build failures while Airflow is running.
- These changes are for local development infrastructure; avoid publishing the application with default passwords or without authentication.
