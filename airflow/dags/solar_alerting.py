"""Webhook alert callbacks for Airflow 3.x.

Uses the Python standard library so DAG parsing needs no extra packages.
Secrets are read only from environment variables; delivery never blocks a DAG.
"""
from __future__ import annotations

import json
import logging
import os
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)


def render_failure(context: dict) -> str:
    """Render a bounded message without copying potentially sensitive exceptions."""
    dag_run = context.get("dag_run")
    task_instance = context.get("task_instance")
    dag_id = getattr(dag_run, "dag_id", None) or getattr(task_instance, "dag_id", "unknown")
    run_id = getattr(dag_run, "run_id", None) or context.get("run_id", "unknown")
    task_id = getattr(task_instance, "task_id", "unknown")
    # Avoid sending exception payloads, environment data, or connection strings.
    return (
        "[E2E Solar] Airflow DAG FAILED\n"
        f"DAG: {str(dag_id)[:120]}\n"
        f"Task context: {str(task_id)[:120]}\n"
        f"Run: {str(run_id)[:180]}\n"
        "Inspect the Airflow UI (http://localhost:8080) for task details."
    )


def send_alert(
    message: str,
    *,
    webhook_url: str | None = None,
    alert_format: str | None = None,
) -> bool:
    """Send a Slack or Discord webhook. Return False when not configured.

    Raises for provider/network errors; callers should handle them explicitly.
    """
    url = webhook_url if webhook_url is not None else os.getenv("SOLAR_ALERT_WEBHOOK_URL", "")
    if not url.strip():
        LOGGER.info("Alert webhook not configured; message: %s", message)
        return False
    if not url.startswith("https://"):
        raise ValueError("SOLAR_ALERT_WEBHOOK_URL must start with https://")

    provider = (alert_format or os.getenv("SOLAR_ALERT_FORMAT", "discord")).lower().strip()
    if provider == "discord":
        body = {"content": message[:1900]}
    elif provider == "slack":
        body = {"text": message[:1900]}
    else:
        raise ValueError("SOLAR_ALERT_FORMAT must be 'discord' or 'slack'")

    data = json.dumps(body).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "e2e-solar-alerts/1"},
        method="POST",
    )
    with urlopen(request, timeout=7) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Alert provider rejected request (HTTP {response.status})")
    LOGGER.info("Airflow alert delivered via %s", provider)
    return True


def notify_dag_failure(context: dict) -> None:
    """Dag-level on_failure_callback; sends one alert after retries are exhausted."""
    try:
        send_alert(render_failure(context))
    except Exception:
        # Critical: notification failure must not hide the original DAG failure.
        # Do not log the request URL: webhook URLs contain secrets.
        LOGGER.error("Airflow failure alert delivery did not succeed", exc_info=False)
