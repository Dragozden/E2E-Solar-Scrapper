# Stage 11.5c — wide STC table regression

This patch uses the origin of the electrical STC heading to support wider right-hand tables (Risen). The original fixed half-page fallback is retained for left-side layouts and split titles. A footnote starting `STC:` terminates the spatial data region; NMOT/rear-side boundaries and the checks on duplicate rows, counts, alignment and physics remain in place. This is a bounded layout improvement, not a universal PDF parser.

Tested with pdfplumber 0.11.9 on the two uploaded original documents:

- Risen: SHA-256 `09917077072c42473e52297b531ed9c604d1fb5bd4f2cc773fdf42007d518b41`. Page 2, zero-based column 3, STC 620 W, Voc 49.08 V, Vmp 40.81 V, Isc 16.04 A, Imp 15.20 A, efficiency 23.0%. `REVIEW_REQUIRED`, not a database write.
- TW Solar: SHA-256 `5c8e80c270b43b0aee28aada5af1f1ff55b359403a50629ff70fba022d4ccdb9`. Only 180 extracted text characters; visual page 1 says TWMND, page 2 header says TWMNH, STC model row says TWMND-72HDXXX. Still refused, with an explicit limited-text-layer hint. Do not bypass family checks, generate a fake review, or assume the conflicting header is a typo. Obtain a confirmed/corrected datasheet. No OCR is implemented in this patch.

## Windows PowerShell

Extract the patch into the repository root, replacing only the two Python source files and adding the test and documentation. Run:

```powershell
uv run --frozen python -m pytest tests/test_panel_pdf_wide_columns.py -q
uv run --frozen python -m pytest -q
$dir = Join-Path $HOME 'Downloads\SolarSpecs'
uv run --frozen --with 'pdfplumber==0.11.9' python scripts/panel_pdf_preview.py --pdf "$dir\Risen_620.pdf" --model 'RSM132-11-620BN' --power 620 --json-output "$dir\Risen_620_review_v2.json"
```

Expected: five new tests; 427 total if starting from 422. Original report files are intentionally not overwritten. Use a new filename if needed. Verify page 2, fourth STC column, then preview the existing approval command:

```powershell
$url = 'https://sklepsoltech.pl/pl/p/Panel-fotowoltaiczny-Risen-RSM132-11-620BN-DG-Bifacial/4013'
uv run --frozen python scripts/approve_panel_pdf.py --pdf "$dir\Risen_620.pdf" --review-json "$dir\Risen_620_review_v2.json" --source-url $url --confirm-model 'RSM132-11-620BN'
```

Only after manual verification and successful PREVIEW_ONLY, rerun with `--approve`. No migration or dbt model change is needed. Check `scripts/check_panel_spec_models.py --min-complete 7` and `scripts/panel_spec_batch.py status`.

Local tests: 85 PDF extraction/approval tests passed, using prior patch sources; full project and real database were not executed here. The actual original TW 500/505 document was not available for this regression; earlier synthetic cases pass. No original manufacturer PDF or generated review JSON is bundled into the patch. No pricing/history mutations.
