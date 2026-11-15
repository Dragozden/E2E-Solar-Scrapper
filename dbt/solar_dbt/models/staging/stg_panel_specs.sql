-- Grain: one saved, immutable spec version (spec_id). No deduplication at Bronze/Silver.
-- JSONB remains in Bronze; this model exposes conservative typed fields.
-- This view can be empty before the first manual --write, without breaking dbt.
WITH extracted AS (
    SELECT
        s.spec_id,
        s.source_url,
        s.fetched_at,
        s.page_title,
        s.spec_hash,
        s.parser_version,
        s.attributes_raw,
        s.normalized_values,
        s.datasheet_urls,
        s.parse_issues,
        CASE
            WHEN jsonb_typeof(s.parse_issues) = 'array' THEN jsonb_array_length(s.parse_issues)
            ELSE 1
        END AS parse_issue_count,
        NULLIF(BTRIM(s.normalized_values ->> 'manufacturer'), '') AS manufacturer,
        NULLIF(BTRIM(s.normalized_values ->> 'model'), '') AS model,
        NULLIF(BTRIM(s.normalized_values ->> 'cell_technology'), '') AS cell_technology,
        {{ solar_json_number('s.normalized_values', 'rated_power_w') }} AS rated_power_w,
        {{ solar_json_number('s.normalized_values', 'efficiency_pct') }} AS efficiency_pct,
        {{ solar_json_number('s.normalized_values', 'voc_v') }} AS voc_v,
        {{ solar_json_number('s.normalized_values', 'vmp_v') }} AS vmp_v,
        {{ solar_json_number('s.normalized_values', 'isc_a') }} AS isc_a,
        {{ solar_json_number('s.normalized_values', 'imp_a') }} AS imp_a,
        {{ solar_json_number('s.normalized_values', 'bifaciality_pct') }} AS bifaciality_pct,
        {{ solar_json_number('s.normalized_values', 'cell_count') }} AS cell_count,
        {{ solar_json_number('s.normalized_values', 'area_m2') }} AS area_m2,
        {{ solar_json_number('s.normalized_values', 'power_density_w_m2') }} AS power_density_w_m2,
        {{ solar_json_number('s.normalized_values', 'mass_kg') }} AS mass_kg,
        {{ solar_json_number('s.normalized_values', 'max_system_voltage_v') }} AS max_system_voltage_v,
        {{ solar_json_number('s.normalized_values', 'max_series_fuse_a') }} AS max_series_fuse_a,
        {{ solar_json_number('s.normalized_values', 'temp_coeff_pmax_pct_c') }} AS temp_coeff_pmax_pct_c,
        {{ solar_json_number('s.normalized_values', 'temp_coeff_voc_pct_c') }} AS temp_coeff_voc_pct_c,
        {{ solar_json_number('s.normalized_values', 'temp_coeff_isc_pct_c') }} AS temp_coeff_isc_pct_c,
        {{ solar_json_number('s.normalized_values', 'nmot_c') }} AS nmot_c,
        {{ solar_json_number('s.normalized_values', 'product_warranty_years') }} AS product_warranty_years,
        {{ solar_json_number('s.normalized_values', 'performance_warranty_years') }} AS performance_warranty_years
    FROM {{ source('solar_bronze', 'panel_spec_snapshots') }} s
),
checked AS (
    SELECT
        *,
        (
            rated_power_w > 0
            AND voc_v > 0 AND vmp_v > 0
            AND isc_a > 0 AND imp_a > 0
        ) IS TRUE AS has_core_electrical_fields,
        (
            voc_v > vmp_v
            AND isc_a >= imp_a
            AND ABS(rated_power_w - (vmp_v * imp_a)) <= rated_power_w * 0.12
        ) IS TRUE AS electrical_consistency_pass
    FROM extracted
)
SELECT
    *,
    CASE
        WHEN NOT has_core_electrical_fields THEN 'INCOMPLETE'
        WHEN NOT electrical_consistency_pass OR parse_issue_count > 0 THEN 'REVIEW'
        ELSE 'PASS'
    END AS spec_quality
FROM checked
