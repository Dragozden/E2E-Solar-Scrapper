# E2E Solar — Step 11.5a: local PDF/STC inspector (read-only)

## Scope and safety

This is **not** automated PDF enrichment and is not connected to Airflow, dbt or PostgreSQL. The tool reads an **already downloaded local PDF**, finds a candidate numeric column of its **STC** electrical table for a precisely specified panel wattage, then prints an auditable JSON preview. There is no database connector, no remote HTTP, no automatic merge or write.

**Treat even a successful result as `REVIEW_REQUIRED`.** Verify the manufacturer's PDF version, the full model family, the correct STC table, and the exact power variant against the actual page before building an import stage. Revisions of the same model family can have different parameters. Similar names and power alone do not establish identical hardware.

The initial Soltech links come directly from the existing Gold model's `datasheet_urls` (do not add these documents to the Git repository):

| Catalog | Local PDF filename suggestion | Product URL to inspect manually |
|---|---|---|
| TW Solar 505 W | `TW_505.pdf` | https://sklepsoltech.pl/pl/p/file/cb085212bb006a7daac4a190973bda93/Karta-katalogowa-TW-Solar-TWMNH-54HD-495-515-W-PL.pdf |
| TW Solar 500 W | `TW_500.pdf` | https://sklepsoltech.pl/pl/p/file/c92c05030efd938483a50e1fe334ef73/Karta-katalogowa-TW-Solar-TWMNH-54HD-495-515-W-PL.pdf |
| TW Solar 590 W | `TW_590.pdf` | https://sklepsoltech.pl/pl/p/file/5562af97f46c29466a3a0fc9647dfd36/Karta-Katalogowa-TWMND-72HD590W-PL.pdf |
| Risen 620 W | `Risen_620.pdf` | https://sklepsoltech.pl/pl/p/file/93b34d1ce0e2c0619656ed143d804eda/Risen-Energy-RSM132-11-605-630BNDG-IEC1500V-30mm-2025H1-2-Datasheet-en.pdf |

The first two have the same download **basename** but different URLs. Save them to separate files, and use `pdf_sha256` to tell versions apart. Do not infer they are bit-identical.

## How to run on Windows PowerShell

1. Download each PDF manually through your browser and save it under `$HOME\Downloads\SolarSpecs\` (outside the repository).
2. Extract the ZIP into the project root, preserving its `scripts/`, `scraper/`, `tests/` and `docs/` directories.
3. Execute:

```powershell
cd "E:\Repos Projects\E2E Solar Scrapper"
uv run --frozen python -m pytest tests/test_panel_pdf_stc.py tests/test_panel_pdf_cli.py -q
uv run --frozen python -m pytest -q

uv run --frozen --with "pdfplumber==0.11.9" python scripts/panel_pdf_preview.py `
  --pdf "$HOME\Downloads\SolarSpecs\TW_505.pdf" `
  --model "TWMNH-54HD505" --power 505 `
  --json-output "$HOME\Downloads\SolarSpecs\TW_505_review.json"
```

For additional variants:

```powershell
uv run --frozen --with "pdfplumber==0.11.9" python scripts/panel_pdf_preview.py --pdf "$HOME\Downloads\SolarSpecs\TW_500.pdf" --model "TWMNH-54HD500" --power 500
uv run --frozen --with "pdfplumber==0.11.9" python scripts/panel_pdf_preview.py --pdf "$HOME\Downloads\SolarSpecs\TW_590.pdf" --model "TWMND-72HD590W" --power 590
uv run --frozen --with "pdfplumber==0.11.9" python scripts/panel_pdf_preview.py --pdf "$HOME\Downloads\SolarSpecs\Risen_620.pdf" --model "RSM132-11-620BNDG" --power 620
```

`--with` provides an optional ephemeral dependency without changing `uv.lock` or the container images. If internet package installation is unavailable, resolve this dependency through the normal approved package workflow; do not edit the package lock by hand.

## Reading the result

- `REVIEW_REQUIRED` with one candidate: a STC column was located but **still needs visual confirmation**.
- `NO_UNAMBIGUOUS_STC_TABLE`: unsupported PDF layout, image-only document, no matching variant, multiple tables, missing model family or insufficient values. This is an expected safe failure, **not a reason to fill values heuristically**. Inspect `diagnostics` and PDF manually.
- The tool checks 5 required STC values (`Pmax`, `Voc`, `Isc`, `Vmp`, `Imp`), their table column counts and basic physics. `efficiency_pct` is optional but extracted when present.
- `page` is 1-based, `variant_column_zero_based` is a zero-based index **among power variants**, `pdf_sha256` identifies the exact local PDF, and `database_write` is always false.
- The inspector does not interpret row values from NMOT/NOCT, BNPI, or rear-side gain as STC.

## Non-goals and next phase

- The extractor is conservative and may refuse legitimate but irregularly laid-out manufacturer PDF tables. That is preferable to storing an invented specification. No OCR, remote downloads, hidden retries, or database inserts.
- Never insert a second PDF-derived snapshot directly using the HTML parser's `spec_hash`: Stage 11.5b must implement a separate, provenance-aware import with document SHA-256, page, model variant, verified fields, and explicit review approval.
- The Jolywood 630 W `conflicting_bifaciality_pct`, `conflicting_imp_a`, `conflicting_isc_a` must be investigated separately. There is no verified PDF link in its latest Bronze snapshot.

## Repository hygiene

The existing step 11.4 and 11.4a are **not staged** in the user's last `git status`. After tests and review, stage only the relevant files (do **not** `git add .`):

```powershell
git add scripts/panel_spec_batch.py scripts/migrate_panel_spec_batch.py docker/postgres/init/007_panel_spec_attempts.sql tests/test_panel_spec_batch.py docs/panel_spec_batch_11_4.md
git add scraper/load.py scripts/diagnose_db_latency.py tests/test_db_latency_probe.py docs/db_latency_step11_4a.md
git add scraper/panel_pdf_stc.py scripts/panel_pdf_preview.py tests/test_panel_pdf_stc.py tests/test_panel_pdf_cli.py docs/panel_pdf_review_11_5a.md

git diff --cached --check
git diff --cached --stat
git diff --cached --name-only
```

Review `git diff --cached` (especially `scraper/load.py`), commit and push only after confirming the contents. Keep `.env`, `.env.example` pending changes, existing `INSTALL_*` notes, unrelated security scripts and downloaded PDF files out of this commit unless deliberately reviewed and needed. This stage does not migrate or remove any tables, rebuild Docker, or edit the pricing pipeline.
