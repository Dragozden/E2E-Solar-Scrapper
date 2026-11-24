-- Grain: exactly one row per current price-ranking URL.
-- HTML snapshots are immutable. A newer approved PDF/STC variant is used for
-- electrical fields only, with all original HTML metadata and warnings retained.
WITH ranked_html AS (
    SELECT s.*,
        ROW_NUMBER() OVER (PARTITION BY s.source_url
            ORDER BY s.fetched_at DESC, s.spec_id DESC) AS rn
    FROM {{ ref('stg_panel_specs') }} s
),
latest_html AS (
    SELECT * FROM ranked_html WHERE rn = 1
),
ranked_pdf AS (
    SELECT p.*,
        ROW_NUMBER() OVER (PARTITION BY p.source_url
            ORDER BY p.approved_at DESC, p.approval_id DESC) AS rn
    FROM {{ ref('stg_panel_pdf_approvals') }} p
),
latest_pdf AS (
    SELECT * FROM ranked_pdf WHERE rn = 1
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
        s.spec_quality AS html_spec_quality,
        s.parse_issue_count AS html_parse_issue_count,
        CASE
            WHEN p.approval_method = 'local_pdf_ocr_manual_v1' AND (
                CASE WHEN jsonb_typeof(s.parse_issues) = 'array' THEN
                    (s.parse_issues - ARRAY[
                        'conflicting_rated_power_w', 'conflicting_voc_v', 'conflicting_vmp_v',
                        'conflicting_isc_a', 'conflicting_imp_a', 'conflicting_efficiency_pct'
                    ]::text[]) <> '[]'::jsonb
                ELSE TRUE END
            ) THEN 'REVIEW'
            WHEN p.approval_id IS NOT NULL THEN p.pdf_quality
            ELSE s.spec_quality END AS spec_quality,
        s.parse_issue_count,
        s.parse_issues,
        s.datasheet_urls,
        s.manufacturer,
        COALESCE(p.model, s.model) AS model,
        s.cell_technology,
        COALESCE(p.rated_power_w, s.rated_power_w) AS technical_power_w,
        COALESCE(p.efficiency_pct, s.efficiency_pct) AS efficiency_pct,
        COALESCE(p.voc_v, s.voc_v) AS voc_v,
        COALESCE(p.vmp_v, s.vmp_v) AS vmp_v,
        COALESCE(p.isc_a, s.isc_a) AS isc_a,
        COALESCE(p.imp_a, s.imp_a) AS imp_a,
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
        (s.spec_id IS NOT NULL OR p.approval_id IS NOT NULL) AS has_specification,
        CASE WHEN COALESCE(p.rated_power_w, s.rated_power_w) IS NULL THEN NULL
             ELSE ABS(r.power_w::NUMERIC - COALESCE(p.rated_power_w, s.rated_power_w)) <= 1
        END AS spec_power_matches_catalog,
        CASE WHEN p.approval_id IS NOT NULL THEN 'PDF_APPROVED'
             WHEN s.spec_id IS NOT NULL THEN 'HTML'
             ELSE 'NONE' END AS technical_source,
        p.approval_id AS pdf_approval_id,
        p.pdf_sha256,
        p.review_sha256 AS pdf_review_sha256,
        p.pdf_url AS pdf_source_url,
        p.pdf_page,
        p.variant_column AS pdf_variant_column,
        p.approved_at AS pdf_approved_at,
        p.approval_method AS pdf_approval_method,
        p.ocr_evidence_sha256 AS pdf_ocr_evidence_sha256,
        p.pdf_quality AS pdf_stc_quality
    FROM {{ ref('current_panel_ranking') }} r
    LEFT JOIN latest_html s ON r.source_url = s.source_url
    LEFT JOIN latest_pdf p ON r.source_url = p.source_url
)
SELECT
    overall_rank,
    scrape_id,
    scrape_run_id,
    title,
    source_url,
    price_pln,
    catalog_power_w,
    pln_per_watt,
    watt_per_pln,
    price_category,
    is_available,
    scraped_at,
    spec_id,
    spec_fetched_at,
    parser_version,
    spec_hash,
    spec_page_title,
    spec_quality,
    parse_issue_count,
    parse_issues,
    datasheet_urls,
    manufacturer,
    model,
    cell_technology,
    technical_power_w,
    efficiency_pct,
    voc_v,
    vmp_v,
    isc_a,
    imp_a,
    bifaciality_pct,
    cell_count,
    area_m2,
    power_density_w_m2,
    mass_kg,
    max_system_voltage_v,
    max_series_fuse_a,
    temp_coeff_pmax_pct_c,
    temp_coeff_voc_pct_c,
    temp_coeff_isc_pct_c,
    nmot_c,
    product_warranty_years,
    performance_warranty_years,
    has_specification,
    spec_power_matches_catalog,
    CASE
        WHEN NOT has_specification THEN 'NOT_ENRICHED'
        WHEN spec_quality = 'PASS' AND spec_power_matches_catalog IS FALSE THEN 'POWER_MISMATCH'
        ELSE spec_quality
    END AS technical_status,
    (spec_quality = 'PASS' AND spec_power_matches_catalog IS TRUE) IS TRUE
        AS is_technical_comparable,
    -- New columns are appended after ALL legacy columns to preserve
    -- PostgreSQL CREATE OR REPLACE VIEW compatibility and dashboard consumers.
    technical_source,
    html_spec_quality,
    html_parse_issue_count,
    pdf_approval_id,
    pdf_sha256,
    pdf_review_sha256,
    pdf_source_url,
    pdf_page,
    pdf_variant_column,
    pdf_approved_at,
    pdf_approval_method,
    pdf_ocr_evidence_sha256,
    pdf_stc_quality
FROM combined
