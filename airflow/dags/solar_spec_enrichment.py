"""Manual-only Airflow 3 pilot for bounded technical HTML enrichment."""
from datetime import timedelta

import pendulum
from airflow.sdk import dag, task, get_current_context
from solar_alerting import notify_dag_failure
from solar_spec_enrichment_commands import (
    DEFAULTS, plan_command, batch_command, check_commands, run_command,
)


def config():
    # Read explicit run configuration instead of relying on params override settings.
    conf = get_current_context()["dag_run"].conf
    return {} if conf is None else conf


@dag(
    dag_id="solar_spec_enrichment",
    description="Manual bounded HTML enrichment; no PDF approvals",
    start_date=pendulum.datetime(2026, 11, 24, tz="Europe/Warsaw"),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=True,
    default_args={"retries": 0},
    params=DEFAULTS.copy(),
    on_failure_callback=notify_dag_failure,
    tags=["solar", "enrichment", "manual"],
)
def solar_spec_enrichment():
    @task(execution_timeout=timedelta(minutes=3))
    def plan_batch():
        run_command(plan_command(config()), timeout=120)

    @task(
    execution_timeout=timedelta(minutes=15),
    pool="solar_source_access",
)
    def enrich_batch():
        command = batch_command(config())
        if command is None:
            print("PLAN_ONLY: no HTTP requests or specification writes", flush=True)
            return
        # Existing CLI enforces bounded requests, local lock and stop-on-error.
        # A manual operator must keep other scrapers stopped during this run.
        run_command(command, timeout=720)

    @task(execution_timeout=timedelta(minutes=3))
    def validate_coverage():
        for command in check_commands():
            run_command(command, timeout=60)

    plan_batch() >> enrich_batch() >> validate_coverage()


solar_spec_enrichment()
