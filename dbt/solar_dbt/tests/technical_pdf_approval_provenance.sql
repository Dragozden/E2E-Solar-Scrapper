-- Every comparable approved PDF row must be model/power valid and traceable.
SELECT source_url, pdf_approval_id, technical_status, technical_power_w, catalog_power_w
FROM {{ ref('panel_technical_comparison') }}
WHERE technical_source = 'PDF_APPROVED'
  AND is_technical_comparable IS TRUE
  AND (pdf_approval_id IS NULL OR pdf_sha256 IS NULL OR pdf_source_url IS NULL
       OR spec_quality <> 'PASS' OR technical_status <> 'PASS'
       OR technical_power_w IS DISTINCT FROM catalog_power_w)
