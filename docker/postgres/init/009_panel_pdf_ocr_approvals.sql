-- Extend existing append-only approval evidence with a distinct OCR method.
ALTER TABLE bronze.panel_pdf_approvals ADD COLUMN IF NOT EXISTS ocr_evidence_sha256 TEXT;
ALTER TABLE bronze.panel_pdf_approvals DROP CONSTRAINT IF EXISTS panel_pdf_approvals_approval_method_check;
ALTER TABLE bronze.panel_pdf_approvals ADD CONSTRAINT panel_pdf_approvals_approval_method_check
    CHECK (approval_method IN ('local_pdf_manual_v1', 'local_pdf_ocr_manual_v1'));
ALTER TABLE bronze.panel_pdf_approvals DROP CONSTRAINT IF EXISTS panel_pdf_approvals_ocr_evidence_check;
ALTER TABLE bronze.panel_pdf_approvals ADD CONSTRAINT panel_pdf_approvals_ocr_evidence_check
    CHECK ((approval_method = 'local_pdf_manual_v1' AND ocr_evidence_sha256 IS NULL)
        OR (approval_method = 'local_pdf_ocr_manual_v1' AND ocr_evidence_sha256 IS NOT NULL
            AND ocr_evidence_sha256 ~ '^[a-f0-9]{64}$'));
