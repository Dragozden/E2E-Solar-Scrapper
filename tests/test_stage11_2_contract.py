"""Offline checks for Stage 11.2 SQL contracts; integration runs in GitHub Actions PG17."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

from scripts.check_panel_spec_models import ComparisonCounts, validate_counts

ROOT = Path(__file__).resolve().parents[1]
DBT = ROOT / "dbt" / "solar_dbt"


def read(path: str) -> str:
    return (DBT / path).read_text(encoding="utf-8")


def test_bronze_source_declares_specs():
    config = yaml.safe_load(read("models/staging/source.yml"))
    assert config["sources"][0]["name"] == "solar_bronze"
    assert set(t["name"] for t in config["sources"][0]["tables"]) == {
        "panel_scrape_raw", "scrape_runs", "panel_spec_snapshots"
    }


def test_specs_staging_references_immutable_source_and_quality_fields():
    sql = read("models/staging/stg_panel_specs.sql")
    assert "source('solar_bronze', 'panel_spec_snapshots')" in sql
    assert "s.spec_id" in sql and "s.spec_hash" in sql
    assert "'INCOMPLETE'" in sql and "'REVIEW'" in sql and "'PASS'" in sql
    assert "jsonb_array_length" in sql
    assert "vmp_v * imp_a" in sql
    assert "solar_json_number" in sql


def test_safe_numeric_conversion_is_guarded():
    sql = read("macros/solar_json_number.sql")
    assert "NUMERIC(14,4)" in sql
    assert "::NUMERIC" in sql
    assert "LENGTH(" in sql
    assert "CASE" in sql and "ELSE NULL" in sql


def test_latest_spec_dedup_and_outer_join():
    sql = read("models/marts/panel_technical_comparison.sql")
    assert "ROW_NUMBER() OVER" in sql
    assert "PARTITION BY s.source_url" in sql
    assert "ORDER BY s.fetched_at DESC, s.spec_id DESC" in sql
    assert "WHERE latest_version_rank = 1" in sql
    assert "LEFT JOIN latest_specs" in sql
    assert "ref('current_panel_ranking')" in sql
    assert "is_technical_comparable" in sql


def test_new_models_do_not_mutate_bronze_or_existing_gold():
    for relative in ["models/staging/stg_panel_specs.sql", "models/marts/panel_technical_comparison.sql"]:
        sql = read(relative).upper()
        assert not any(token in sql for token in ("DROP TABLE", "TRUNCATE ", "DELETE FROM", "UPDATE ", "INSERT INTO"))


def test_model_schema_quality_tests():
    for path in ("models/staging/stg_panel_specs.yml", "models/marts/panel_technical_comparison.yml"):
        config = yaml.safe_load(read(path))
        assert config["version"] == 2
        assert config["models"][0]["columns"]
    quality = yaml.safe_load(read("models/marts/panel_technical_comparison.yml"))["models"][0]
    assert any("accepted_values" in item for column in quality["columns"]
               for item in column.get("data_tests", []) if isinstance(item, dict))


def test_sql_data_quality_checks_refer_to_new_view():
    for path in ("tests/technical_comparison_preserves_catalog.sql",
                 "tests/technical_comparison_only_qualified.sql"):
        assert "ref('panel_technical_comparison')" in read(path)


def test_check_counts_passes():
    validate_counts(ComparisonCounts(72, 72, 2, 1, 0, 69, 0), 2)

@pytest.mark.parametrize("counts,min_complete", [
    (ComparisonCounts(72, 71, 2, 1, 0, 68, 0), 0),
    (ComparisonCounts(72, 72, 1, 1, 0, 70, 0), 2),
    (ComparisonCounts(72, 72, 2, 1, 0, 70, 0), 0),
])
def test_check_counts_catches_errors(counts, min_complete):
    with pytest.raises(RuntimeError):
        validate_counts(counts, min_complete)


def test_ci_sample_script_guard_not_bypassed():
    fixture = (ROOT / "scripts" / "ci_panel_specs.py").read_text()
    assert "from scripts.ci_dbt_integration import PREFIX, connection" in fixture
    assert '"seed", "assert"' in fixture
    assert "SYNTHETIC-ONLY" in fixture
    assert 'spec_hash' in fixture
    ast.parse(fixture)
