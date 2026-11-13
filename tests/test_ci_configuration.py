"""Static checks for the CI contract. No Docker or database required."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow():
    # BaseLoader prevents YAML 1.1 interpreting 'on' as Boolean True.
    return yaml.load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_ci_exercises_python_dbt_and_docker():
    jobs = workflow()["jobs"]
    assert {"python-tests", "dbt-integration", "docker-build"} <= set(jobs)
    assert "postgres" in jobs["dbt-integration"]["services"]
    assert jobs["dbt-integration"]["services"]["postgres"]["image"] == "postgres:17"


def test_ci_has_no_push_to_registry_or_production():
    raw = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "docker push" not in raw
    assert "docker/login-action" not in raw
    assert "permissions:\n  contents: read" in raw
    assert "scripts/ci_dbt_integration.py seed" in raw
    assert "scripts/ci_dbt_integration.py assert" in raw


def test_ci_fixture_requires_explicit_ephemeral_environment():
    src = (ROOT / "scripts/ci_dbt_integration.py").read_text(encoding="utf-8")
    assert 'os.getenv("GITHUB_ACTIONS")' in src
    assert 'os.getenv("POSTGRES_DB") != "solar_prices"' in src
    assert 'docker" / "postgres" / "init"' in src
