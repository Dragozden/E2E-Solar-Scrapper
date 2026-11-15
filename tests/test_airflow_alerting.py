"""Offline tests: no Airflow dependency, no outbound HTTP requests."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "solar_alerting", ROOT / "airflow" / "dags" / "solar_alerting.py"
)
ALERTING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ALERTING)


class FakeResponse:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def test_render_failure_contains_dag_and_run_but_not_exception():
    context = {
        "dag_run": SimpleNamespace(dag_id="solar_el_pipeline", run_id="scheduled__2026-11-15"),
        "task_instance": SimpleNamespace(task_id="build_dbt_models"),
        "exception": "POSTGRES_PASSWORD=super-secret",
    }
    result = ALERTING.render_failure(context)
    assert "solar_el_pipeline" in result
    assert "build_dbt_models" in result
    assert "scheduled__2026-11-15" in result
    assert "super-secret" not in result


def test_unconfigured_webhook_does_not_make_a_request(monkeypatch):
    monkeypatch.delenv("SOLAR_ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(ALERTING, "urlopen", lambda *_a, **_k: pytest.fail("network used"))
    assert ALERTING.send_alert("test") is False


@pytest.mark.parametrize("provider,field", [("discord", "content"), ("slack", "text")])
def test_webhook_message_format(monkeypatch, provider, field):
    captured = {}

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(ALERTING, "urlopen", fake_urlopen)
    assert ALERTING.send_alert("offline test", webhook_url="https://example.test/webhook/secret", alert_format=provider)
    assert captured["request"].get_method() == "POST"
    assert json.loads(captured["request"].data) == {field: "offline test"}
    assert captured["timeout"] <= 10


def test_reject_insecure_webhook():
    with pytest.raises(ValueError, match="https"):
        ALERTING.send_alert("test", webhook_url="http://localhost/hook")


def test_reject_unknown_webhook_type():
    with pytest.raises(ValueError, match="discord"):
        ALERTING.send_alert("test", webhook_url="https://example.test/hook", alert_format="teams")


def test_notify_failure_never_breaks_callback(monkeypatch):
    monkeypatch.setattr(ALERTING, "send_alert", lambda *a, **kw: (_ for _ in ()).throw(OSError("down")))
    assert ALERTING.notify_dag_failure({}) is None
