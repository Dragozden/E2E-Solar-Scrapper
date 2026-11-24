SELECT source_url
FROM {{ ref('panel_technical_comparison') }}
WHERE pdf_approval_method = 'local_pdf_ocr_manual_v1'
AND (pdf_ocr_evidence_sha256 IS NULL OR pdf_ocr_evidence_sha256 !~ '^[a-f0-9]{64}$'
     OR technical_source IS DISTINCT FROM 'PDF_APPROVED'
     OR (technical_status = 'PASS' AND CASE WHEN jsonb_typeof(parse_issues) = 'array' THEN
       (parse_issues - ARRAY['conflicting_rated_power_w', 'conflicting_voc_v', 'conflicting_vmp_v',
         'conflicting_isc_a', 'conflicting_imp_a', 'conflicting_efficiency_pct']::text[]) <> '[]'::jsonb
       ELSE TRUE END))
