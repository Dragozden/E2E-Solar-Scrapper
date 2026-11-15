"""Airflow 3 watchdog: check fresh and valid data every morning at 09:00 Warsaw."""
from datetime import timedelta
import os
import subprocess

import pendulum
from airflow.sdk import dag, task
from solar_alerting import notify_dag_failure

ROOT = "/opt/airflow/solar"
PYTHON = "/opt/airflow/solar-venv/bin/python"


@dag(
    dag_id="solar_data_watchdog",
    description="Check Bronze/Gold freshness and last SUCCESS run integrity",
    start_date=pendulum.datetime(2026, 11, 1, tz="Europe/Warsaw"),
    schedule="0 9 * * *",
    catchup=False,
    max_active_runs=1,
    on_failure_callback=notify_dag_failure,
    tags=["solar", "monitoring", "freshness"],
)
def solar_data_watchdog():
    @task(retries=1, retry_delay=timedelta(minutes=5))
    def check_freshness():
        env = os.environ.copy()
        env["PYTHONPATH"] = ROOT
        subprocess.run([PYTHON, "-m", "scraper.watchdog"], cwd=ROOT, env=env, check=True)

    check_freshness()


solar_data_watchdog()
