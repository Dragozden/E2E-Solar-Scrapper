# Step 11.5d — bounded PDF review queue (pilot)

## Scope

The queue reads current `INCOMPLETE` and `REVIEW` products from Gold in an explicitly read-only transaction. It never updates Bronze, writes approvals, changes dbt or runs Airflow. `plan` uses only PostgreSQL plus local directory existence checks, and does not download anything. `run --download` is an explicit opt-in; check the retailer's terms and robots policy before running. Never run alongside another detail scraper. The standard-library robots parser is a preliminary check, not a substitute for verifying the current site policy. Do not circumvent access restrictions; if robots is unavailable or the HTTP request fails, stop and investigate.

Only the first trusted linked PDF (the same selection used by the existing importer) is considered, under the retailer's `/pl/p/file/.../*.pdf` path. No redirects, retries, or external-host discovery. At most ten jobs per run, ten seconds minimum delay (longer if robots specifies a greater delay), 20 MiB max response per PDF, 20 pages max per parser. A download error stops the batch. A parser refusal saves diagnostics instead of guessing. Missing or ambiguous model names are NOT guessed from the title. Optional `--model-map` accepts an explicitly inspected variant, which must still appear in the current catalog title and contain the exact wattage.

## Windows instructions

```powershell
cd "E:\Repos Projects\E2E Solar Scrapper"
uv run --frozen python -m pytest tests/test_panel_pdf_queue.py -q
uv run --frozen python -m pytest -q
uv run --frozen python scripts/panel_pdf_queue.py plan --limit 5
```

Inspect the plan before any network request. `READY` is eligible, not a verified specification. `MODEL_CONFIRMATION_NEEDED` needs a manually checked exact model. `NO_TRUSTED_PDF` and `UNSUPPORTED_PDF_PATH` are skipped. `ALREADY_ATTEMPTED` means a local job directory exists (including interrupted/failed attempts). `selected` lists up to `--limit` READY product URLs. The queue prefers INCOMPLETE, then REVIEW, ordered by current ranking.

```powershell
uv run --frozen --with "pdfplumber==0.11.9" python -u scripts/panel_pdf_queue.py run --limit 3 --download
```

Each attempt creates a local directory under `$HOME\Downloads\SolarSpecs\queue` containing `job.json` (product, exact model, source URL and original issues), `document.pdf` and `review.json` (or `failure.json` on download failure). Job identifiers are derived from product URL, PDF link, model and power. Do not remove or overwrite evidence to force retries; use a fresh `--directory` outside the repository after diagnosing the problem. Stale `.queue.lock` requires verifying no other queue process is running before removing it. The queue is resumable per directory; it is not a distributed lock, and cannot detect changes to a PDF served at an unchanged URL. A previously downloaded report outside the queue is not automatically reused.

Optional model mapping: save a UTF-8 JSON file outside the repository mapping exact product URLs to the manually checked model token, for example:

```json
{
  "https://sklepsoltech.pl/pl/p/Panel-TWMNH-54HD500/3515": "TWMNH-54HD500"
}
```

This URL is illustrative only; use the actual catalog URL printed by `plan`. Pass `--model-map <path>` to both plan and run. If the exact model is not present in the title or does not include the wattage, the job remains blocked.

## Review, not automatic approval

A `REVIEW_REQUIRED` report has one candidate passing the six-field STC check. Verify model family, exact variant, document revision, column and page, and compare the `job.json` PDF URL with the current Gold link. Use `approve_panel_pdf.py` in preview mode with the folder's PDF and review JSON; only use `--approve` after manual review. Do not blindly approve REVIEW products: unresolved conflicts outside the six STC fields (e.g. bifaciality, mechanical ratings or temperatures) are not repaired by PDF STC values. Gold's current PASS semantics can indicate electrical comparability even while HTML parse issues remain; review these separately before relying on other fields. No change to this policy is included in this pilot.

Tests are offline; actual PostgreSQL access and actual retailer HTTP/robots behavior are not verified here. No OCR or generalized model-name inference included. Keep local PDFs, logs and review files out of Git.
