"""Tests for grant preflight; no live database or credentials needed."""
from pathlib import Path

import pytest

from scripts.repair_dashboard_permissions import (
    GOLD_VIEWS,
    READER_ROLE,
    load_local_credentials,
    validate_gold_owners,
)


def test_explicit_reader_and_known_gold_models():
    assert READER_ROLE == "solar_dashboard"
    assert set(GOLD_VIEWS) == {
        "current_panel_ranking", "product_price_history", "daily_market_prices"
    }


def test_grant_check_requires_all_gold_views():
    with pytest.raises(RuntimeError, match="Brak widoków Gold: daily_market_prices"):
        validate_gold_owners({"current_panel_ranking": "postgres", "product_price_history": "postgres"})


def test_valid_relation_owners():
    validate_gold_owners({name: "postgres" for name in GOLD_VIEWS})


def test_passwords_are_loaded_without_printing_or_overwriting(tmp_path):
    path = tmp_path / ".env"
    path.write_text("POSTGRES_DB=solar_prices\nPOSTGRES_USER=postgres\nPOSTGRES_PASSWORD=secret123\n")
    loaded = load_local_credentials(path)
    assert loaded["user"] == "postgres"
    assert loaded["password"] == "secret123"
    assert loaded["host"] == "localhost"
    assert path.read_text().count("secret123") == 1


def test_no_recovery_file_is_implicitly_created(tmp_path):
    path = tmp_path / "missing.env"
    with pytest.raises(RuntimeError, match="Brak pliku"):
        load_local_credentials(path)
    assert not path.exists()
