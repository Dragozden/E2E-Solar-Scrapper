"""Dedicated read-only query for current technical PV comparisons (dbt Gold).

Intentionally separate from load_gold_data(): a failure of this optional view
must not take down the working ranking, price history, or monitoring tabs.
"""
from __future__ import annotations

import pandas as pd
import psycopg

from dashboard.db import connection_config, _query_dataframe

SQL_TECHNICAL_COMPARISON = """
SELECT
    overall_rank, title, source_url, is_available, price_pln,
    catalog_power_w, pln_per_watt, technical_power_w,
    manufacturer, model, cell_technology,
    efficiency_pct, voc_v, vmp_v, isc_a, imp_a,
    bifaciality_pct, cell_count, area_m2, power_density_w_m2,
    mass_kg, max_system_voltage_v, max_series_fuse_a,
    temp_coeff_pmax_pct_c, temp_coeff_voc_pct_c, temp_coeff_isc_pct_c,
    nmot_c, product_warranty_years, performance_warranty_years,
    spec_fetched_at, technical_status, has_specification,
    is_technical_comparable, parse_issue_count,
    datasheet_urls ->> 0 AS datasheet_url
FROM gold.panel_technical_comparison
ORDER BY overall_rank;
"""

NUMERIC_COLUMNS = (
    "overall_rank", "price_pln", "catalog_power_w", "pln_per_watt",
    "technical_power_w", "efficiency_pct", "voc_v", "vmp_v", "isc_a",
    "imp_a", "bifaciality_pct", "cell_count", "area_m2",
    "power_density_w_m2", "mass_kg", "max_system_voltage_v",
    "max_series_fuse_a", "temp_coeff_pmax_pct_c", "temp_coeff_voc_pct_c",
    "temp_coeff_isc_pct_c", "nmot_c", "product_warranty_years",
    "performance_warranty_years", "parse_issue_count",
)


def load_technical_comparison() -> pd.DataFrame:
    """Query only the dedicated Gold view, under default_transaction_read_only=on."""
    with psycopg.connect(**connection_config()) as conn:
        result = _query_dataframe(conn, SQL_TECHNICAL_COMPARISON)

    for column in NUMERIC_COLUMNS:
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    for column in ("is_available", "has_specification", "is_technical_comparable"):
        if column in result:
            result[column] = result[column].astype("boolean")
    if "spec_fetched_at" in result:
        result["spec_fetched_at"] = pd.to_datetime(result["spec_fetched_at"], errors="coerce")
    return result
