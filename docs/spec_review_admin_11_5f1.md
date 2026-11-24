# Step 11.5f.1 — review usability

Install over 11.5f. Stop the local Streamlit process with Ctrl+C before extracting.

- Catalog filter by technical status and case-insensitive title/model/URL.
- Prefer documents with a reported candidate, then an effective approval; this is a UI ordering hint, not authorization.
- Prefer candidate reports, then OCR and numeric report version; a failed new report does not hide an earlier candidate.
- Show known parser diagnostics, including INSTALLATION_MANUAL_NOT_DATASHEET. Metadata is untrusted and does not replace full validation.
- Existing approval policy and write guards unchanged. No database migration.

Run `uv run --frozen python -m pytest tests/test_spec_review_admin.py -q` (28 tests, symlink test may skip on Windows) and the full suite (552 expected, assuming all prior tests pass).

Start in read-only mode, on loopback only. Verify JA Solar 505 OCR, Risen 450, LONGi 650, and the JA Solar installation manual. Confirm that the manual has no approval form. Do not approve Jinko 435 before verifying revision applicability. Text approvals with unresolved non-STC issues remain blocked. No Streamlit runtime or PostgreSQL integration was exercised in the patch environment.
