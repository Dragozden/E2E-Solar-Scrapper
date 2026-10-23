"""E2E Solar: Playwright -> Bronze -> dbt Silver/Gold -> quality check.

Initially triggered manually. Do not enable scheduling until idempotency is reviewed.
"""
import os
import subprocess
from datetime import timedelta

import pendulum
from airflow.sdk import dag, task

ROOT = "/opt/airflow/solar"
PYTHON = "/opt/airflow/solar-venv/bin/python"
DBT = "/opt/airflow/solar-venv/bin/dbt"


def run_command(command: list[str]) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = ROOT
    subprocess.run(command, cwd=ROOT, env=env, check=True)


@dag(
    dag_id="solar_el_pipeline",
    description="Scrape PV panels and build validated dbt models",
    start_date=pendulum.datetime(2026, 10, 1, tz="Europe/Warsaw"),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=["solar", "elt", "postgres", "dbt"],
)
def solar_pipeline():
    @task(retries=0)
    def scrape_to_bronze():
        # The scraper keeps its own scrape_run_id and SUCCESS/FAILED tracking.
        run_command([PYTHON, "-m", "scraper.main"])

    @task(retries=1, retry_delay=timedelta(minutes=2))
    def build_dbt_models():
        run_command([
            DBT, "build",
            "--project-dir", f"{ROOT}/dbt",
            "--profiles-dir", f"{ROOT}/dbt",
        ])

    @task(retries=0)
    def validate_pipeline():
        run_command([PYTHON, "-m", "scraper.validate"])

    scrape_to_bronze() >> build_dbt_models() >> validate_pipeline()


solar_pipeline()
