# 11.5f — local specification review pilot

Separate Streamlit process; no changes to public app, Docker, Airflow, or DB schema. Requires previous 11.5e.2 and existing Streamlit dependency. Uses local queue under `~/Downloads/SolarSpecs/queue`, no path or file upload input, no external requests. Gold reads explicitly set the transaction to read-only. Original PDFs are downloaded for visual inspection, not embedded. Existing effective approvals are visible but cannot be replaced. This pilot is not a remotely accessible administrative service: it has no user authentication, role provisioning or audit of operator identity. Do not proxy, expose, tunnel, or deploy it to a shared host. Stop it when finished.

## Install and test (Windows PowerShell, repository root)

```powershell
uv run --frozen python -m pytest tests/test_spec_review_admin.py -q
uv run --frozen python -m pytest -q
Remove-Item Env:SOLAR_REVIEW_ENABLE_WRITE -ErrorAction SilentlyContinue
uv run --frozen streamlit run dashboard/spec_review_app.py --server.address 127.0.0.1 --server.port 8502 --server.headless true
```

Open http://127.0.0.1:8502. Main dashboard remains on port 8501. If Streamlit is absent from your local lockfile, report the error; do not change the dependency lock blindly. Verify catalog counts, local queue, Risen 450 W `review.json`, LONGi 650 W `review_v2.json`, JA 505 W `ocr_table_review_page2.json`, and Hyundai 460 W `review_v2.json`. All views are read-only in this run. Existing approvals should have no approve action. JA 505 should retain REVIEW even with PDF STC PASS. Hyundai and LONGi 640 text reports should be blocked for non-STC issues. Jinko 435 requires independent confirmation of regional document before approval, regardless of candidate validity.

## Optional write mode (after pilot acceptance only)

Only on the trusted single-user Windows workstation, with no parallel enrichment or manual approval process. Stop read-only process first. Start with `$env:SOLAR_REVIEW_ENABLE_WRITE = '1'` and the same loopback command. Stop the process with Ctrl+C after review and `Remove-Item Env:SOLAR_REVIEW_ENABLE_WRITE`. The app is not authenticated; local processes with access to the browser/server are within its trust boundary. The DB role is the existing local importer role, not a newly restricted role. Never reuse this environment in the public dashboard. XSRF and CORS must remain enabled.

No approvals are automatic. Type the exact model and confirm that original PDF revision, model, STC column and all six values were inspected. The app revalidates evidence, checks exact catalog PDF URL, compares fingerprint of preview against current data, locks the approval table for serialization and uses existing insert functions. Existing approvals and non-STC text conflicts are blocked. OCR unresolved issues must remain REVIEW. Gold must expose the newly inserted approval and its expected method and STC values, otherwise transaction fails. The lock requires adequate privileges; if rejected, do not escalate blindly. No updates/deletes of prior rows or evidence. The original CLI remains available. This is a single-user pilot, not a robust multi-user service. A concurrent change to catalog data can still occur; avoid parallel enrichment. No reject workflow, complete historical approval timeline, embedded PDF rendering or download/queue automation yet.

## Verification scope

23 new unit tests (symlink case may skip on Windows); 100 tests across admin and approval/reconstruction modules passed in development. Actual diagnostic archive (10 documents) and submitted OCR evidence were validated offline. Archive predates user's later Hyundai review_v2.json. No live PostgreSQL connection or Streamlit runtime was available during development. Write mode uses simulated transactions in tests only; validate read-only UI before enabling write. No new migration.
