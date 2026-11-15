-- An offer must not be flagged as technically comparable without valid
-- detailed specs and a consistent catalog power rating.
SELECT source_url, technical_status, spec_quality, catalog_power_w, technical_power_w
FROM {{ ref('panel_technical_comparison') }}
WHERE is_technical_comparable IS TRUE
  AND (technical_status <> 'PASS'
       OR spec_quality <> 'PASS'
       OR spec_power_matches_catalog IS DISTINCT FROM TRUE)
