# Step 11.5e.1 — OCR table reconstruction pilot

This is an offline evidence-only stage for split model-header JA Solar tables.
It consumes existing `ocr_evidence_pageN.json`; no OCR executable, external
request, database connection or extra dependency is needed. It validates the
original failed report, job model/power, original PDF hash and OCR evidence page.
It clusters words by vertical center, identifies an explicit STC heading,
recovers columns from family and variant suffix rows, aligns numeric tokens by
right edge, requires six labeled rows and stops at the power-tolerance row.
Selected model tokens must score at least 80, numeric tokens at least 85.
Scores are heuristic, not calibrated probabilities. All power columns must
match model variants; Vmp*Imp must agree with Pmax within 2%, and operating
voltage/current must be below open-circuit/short-circuit values respectively.
No missing cells are inferred. Only the observed JA layout is supported; do
not assume other manufacturer layouts or even other JA revisions work.

## Windows

From the repository root after installing the patch:

```powershell
uv run --frozen python -m pytest tests/test_panel_pdf_ocr_table.py -q
uv run --frozen python -m pytest -q
$dir = Join-Path $HOME 'Downloads\SolarSpecs'
$folder = Join-Path $dir 'queue\114aacdf405654e6fcb75699'
uv run --frozen python scripts/reconstruct_panel_pdf_ocr.py --folder $folder --page 2
```

Expected: 16 new tests; `OCR_TABLE_REVIEW_REQUIRED` with 505 W, 44.05 V Voc,
37.11 V Vmp, 14.48 A Isc, 13.61 A Imp, 22.8% efficiency.
Output: `ocr_table_review_page2.json`. Existing reports cannot be overwritten.
The output carries selected token boxes and confidence scores, original PDF
SHA-256 and evidence JSON SHA-256; these are provenance checks, not a signature
or proof that OCR is correct. The fixture contains a cropped subset of the
user-provided OCR tokens (both STC and rear irradiation table); it is not a PDF.

**Do not send this report to the approval CLI or change its status.** It is
intentionally not a `REVIEW_REQUIRED` report and has no `candidates` list.
A separate reviewed OCR approval design is still needed. The existing HTML
bifaciality conflict is outside the scope of these six STC values.
