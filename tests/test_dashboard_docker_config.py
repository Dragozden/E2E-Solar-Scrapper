"""Basic regression checks for Streamlit's Docker deployment configuration."""
from pathlib import Path
import importlib.util

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_compose_has_dashboard_and_pg_healthcheck():
    overlay = yaml.safe_load((ROOT / "docker" / "docker-compose.override.yml").read_text())
    dashboard = overlay["services"]["dashboard"]
    assert dashboard["build"]["dockerfile"] == "dashboard/Dockerfile"
    assert dashboard["env_file"] == ["../dashboard/.env"]
    assert dashboard["ports"] == ["127.0.0.1:8501:8501"]
    assert dashboard["environment"]["POSTGRES_HOST"] == "postgres"
    assert dashboard["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert "healthcheck" in overlay["services"]["postgres"]
    base = yaml.safe_load((ROOT / "docker" / "docker-compose.yml").read_text())
    assert base["services"]["postgres"]["ports"] == ["127.0.0.1:5432:5432"]
    assert base["services"]["pgadmin"]["ports"] == ["127.0.0.1:5050:80"]


def test_reader_secrets_excluded_from_docker_build_context():
    ignore = (ROOT / ".dockerignore").read_text()
    assert "**/.env" in ignore
    assert "**/.env.*" in ignore
    assert "scraper/" not in ignore.replace("# Shared build context for Airflow and Streamlit; do NOT exclude scraper/ or dbt/ source.", "")


def test_bootstrap_reader_env_contains_reader_credentials_not_admin():
    pytest.importorskip("psycopg")
    module_path = ROOT / "scripts" / "setup_dashboard_reader.py"
    spec = importlib.util.spec_from_file_location("setup_dashboard_reader", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    content = module.reader_env_content("solar_prices", "test-password")
    assert "POSTGRES_HOST=postgres" in content
    assert "POSTGRES_USER=solar_dashboard" in content
    assert "POSTGRES_PASSWORD=test-password" in content
    assert "POSTGRES_USER=postgres\n" not in content
