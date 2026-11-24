# 11.5e — full-width STC and OCR evidence pilot

The new text fallback recognizes Hyundai HiT-HxxxLE-FB only if the requested exact variant is printed in the document, the STC series header is explicit, the independent Item/Unit wattage header matches the Pmax row, all six rows have their expected units and align with the same columns. No database or approval changes.

`panel_pdf_ocr.py` is an optional local-only evidence tool. It checks the original queue job and PDF hash, requires a failed original review and refuses a previously recovered review. It renders one low-text page at 250 dpi, calls Tesseract in English and stores OCR words, bounding boxes in pixels and confidence in `ocr_evidence_pageN.json`. This format is deliberately not accepted by the importer. It does not produce a structured candidate, resolve model or other conflicts, or infer missing numbers. Never rename it into a normal approval report. Existing evidence is not overwritten. A separate later stage must validate OCR table geometry and exact model before proposing a structured review.

## Windows

Use Python environment via uv and optional pdfplumber 0.11.9. Tesseract is an external executable, not a Python package; install it separately if needed, including English data. Check `tesseract --version` and `tesseract --list-langs`. If not in PATH, pass `--tesseract 'C:\Program Files\Tesseract-OCR\tesseract.exe'` (if that is the actual installed path).

```
uv run --frozen python -m pytest tests/test_panel_pdf_ocr_pilot.py -q
uv run --frozen python -m pytest -q
$dir = Join-Path $HOME 'Downloads\SolarSpecs'
$folder = Join-Path $dir 'queue\d9b9fd473bd2bc65ca84df6d'
uv run --frozen --with 'pdfplumber==0.11.9' python scripts/panel_pdf_preview.py --pdf "$folder\document.pdf" --model 'HIT-H460LE' --power 460 --json-output "$folder\review_v2.json"
$folder = Join-Path $dir 'queue\114aacdf405654e6fcb75699'
uv run --frozen --with 'pdfplumber==0.11.9' python scripts/panel_pdf_ocr.py --folder $folder --page 2
```

Tests: 140 PDF unit tests passed in the reconstructed local patch tree (10 new). Actual Hyundai, Risen 450 and LONGi 650 extracted and passed STC validation. Real Tesseract 5.5.0 run on JA Solar 505 page 2 produced 528 word tokens. Full corpus rerun exceeded time limit; full repository and Windows Tesseract integration not tested. The remaining warranty, temperature, bifaciality and model inconsistencies are outside this patch.
