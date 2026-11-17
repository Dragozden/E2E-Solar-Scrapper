-- Grain: one immutable manually approved local PDF review, not a current offer.
-- Defensive parsing: malformed manual DB entries must NEVER be marked PASS.
WITH typed AS (
    SELECT
        a.approval_id, a.source_url, a.model, a.power_w, a.pdf_url,
        a.pdf_sha256, a.review_sha256, a.pdf_page, a.variant_column,
        a.approved_at, a.approval_method,
        {{ solar_json_number('a.values_stc', 'rated_power_w') }} AS rated_power_w,
        {{ solar_json_number('a.values_stc', 'voc_v') }} AS voc_v,
        {{ solar_json_number('a.values_stc', 'vmp_v') }} AS vmp_v,
        {{ solar_json_number('a.values_stc', 'isc_a') }} AS isc_a,
        {{ solar_json_number('a.values_stc', 'imp_a') }} AS imp_a,
        {{ solar_json_number('a.values_stc', 'efficiency_pct') }} AS efficiency_pct
    FROM {{ source('solar_bronze', 'panel_pdf_approvals') }} a
)
SELECT
    *,
    CASE
        WHEN rated_power_w BETWEEN 100 AND 900
         AND rated_power_w = power_w
         AND voc_v > vmp_v AND vmp_v > 0 AND voc_v <= 100
         AND isc_a >= imp_a AND imp_a > 0 AND isc_a <= 50
         AND efficiency_pct BETWEEN 10 AND 30
         AND ABS(rated_power_w - vmp_v * imp_a) <= rated_power_w * 0.02
        THEN 'PASS'
        ELSE 'REVIEW'
    END AS pdf_quality
FROM typed
