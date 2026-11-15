-- Grain: precisely one row per source_url in the CURRENT pricing ranking.
-- Latest spec chosen by fetched_at and spec_id; never multiply ranking rows.
-- A newer incomplete spec is not silently replaced with an older valid version.
WITH ranked_spec_versions AS (
    SELECT
        s.*,
        ROW_NUMBER() OVER (
            PARTITION BY s.source_url
            ORDER BY s.fetched_at DESC, s.spec_id DESC
        ) AS latest_version_rank
    FROM {{ ref('stg_panel_specs') }} s
),
latest_specs AS (
    SELECT * FROM ranked_spec_versions WHERE latest_version_rank = 1
),
combined AS (
    SELECT
        r.overall_rank,
        r.scrape_id,
        r.scrape_run_id,
        r.title,
        r.source_url,
        r.price_pln,
        r.power_w AS catalog_power_w,
        r.pln_per_watt,
        r.watt_per_pln,
        r.price_category,
        r.is_available,
        r.scraped_at,
        s.spec_id,
        s.fetched_at AS spec_fetched_at,
        s.parser_version,
        s.spec_hash,
        s.page_title AS spec_page_title,
        s.spec_quality,
        s.parse_issue_count,
        s.parse_issues,
        s.datasheet_urls,
        s.manufacturer,
        s.model,
        s.cell_technology,
        s.rated_power_w AS technical_power_w,
        s.efficiency_pct,
        s.voc_v,
        s.vmp_v,
        s.isc_a,
        s.imp_a,
        s.bifaciality_pct,
        s.cell_count,
        s.area_m2,
        s.power_density_w_m2,
        s.mass_kg,
        s.max_system_voltage_v,
        s.max_series_fuse_a,
        s.temp_coeff_pmax_pct_c,
        s.temp_coeff_voc_pct_c,
        s.temp_coeff_isc_pct_c,
        s.nmot_c,
        s.product_warranty_years,
        s.performance_warranty_years,
        s.spec_id IS NOT NULL AS has_specification,
        CASE
            WHEN s.rated_power_w IS NULL THEN NULL
            ELSE ABS(r.power_w::NUMERIC - s.rated_power_w) <= 1
        END AS spec_power_matches_catalog
    FROM {{ ref('current_panel_ranking') }} r
    LEFT JOIN latest_specs s ON r.source_url = s.source_url
)
SELECT
    *,
    CASE
        WHEN NOT has_specification THEN 'NOT_ENRICHED'
        WHEN spec_quality = 'PASS' AND spec_power_matches_catalog IS FALSE THEN 'POWER_MISMATCH'
        ELSE spec_quality
    END AS technical_status,
    (spec_quality = 'PASS' AND spec_power_matches_catalog IS TRUE) IS TRUE
        AS is_technical_comparable
FROM combined
