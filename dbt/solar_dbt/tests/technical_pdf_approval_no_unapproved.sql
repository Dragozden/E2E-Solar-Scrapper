-- Provenance is mandatory for every Gold row claiming PDF authority.
SELECT source_url
FROM {{ ref('panel_technical_comparison') }}
WHERE (technical_source = 'PDF_APPROVED' AND pdf_approval_id IS NULL)
   OR (technical_source <> 'PDF_APPROVED' AND pdf_approval_id IS NOT NULL)
