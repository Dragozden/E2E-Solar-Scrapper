# E2E Solar — Step 11.1: PV technical specification enrichment pilot

## Intent

The existing daily scraper observes *offers* (price, availability, listing title). This pilot collects *product-page technical specifications* separately and does **not** alter `bronze.panel_scrape_raw`, price history, dbt Gold views, Streamlit, or Airflow. The goal is to validate real product-page markup before enabling any scheduled enrichment.

The example HTML files are **synthetic tests** based on publicly observed label patterns. They are not a verified full HTML capture of the retailer's current DOM. Therefore, an offline PASS does not mean live pages will be parsed correctly. Inspect the preview.

## New data contract

`bronze.panel_spec_snapshots` — one version of technical attributes per `(source_url, spec_hash)`. The version's `spec_hash` is SHA-256 of captured raw label/value pairs, so repeating the same data results in no extra row. A changed specification creates a new snapshot. `fetched_at` uses timezone-aware PostgreSQL `TIMESTAMPTZ` (unlike legacy ingestion timestamps).

| Column | Meaning |
| --- | --- |
| `spec_id` | Unique technical-spec snapshot ID |
| `source_url` | Existing retailer offer URL (still the provisional product identity) |
| `fetched_at` | Ingestion time, UTC-aware in DB |
| `page_title` | Product-page heading |
| `attributes_raw` | Original key/value pairs from the description, including unrecognized fields |
| `normalized_values` | Typed, *optional* technical fields |
| `datasheet_urls` | PDF links only, **no PDF parsing or downloads** |
| `parse_issues` | Validation anomalies and ambiguous fields |
| `spec_hash` | Stable SHA-256 of raw attributes; supports idempotency |
| `parser_version` | Version of parsing rules |

Selected numeric fields in `normalized_values`: `rated_power_w`, `efficiency_pct`, `voc_v`, `vmp_v`, `isc_a`, `imp_a`, `bifaciality_pct`, `dimensions_mm` (array `[length,width,depth]` in mm), `mass_kg`, `temp_coeff_pmax_pct_c`, `temp_coeff_voc_pct_c`, `temp_coeff_isc_pct_c`, `noct_c`, `cell_count`, `max_series_fuse_a`, `max_system_voltage_v`, `product_warranty_years`, `performance_warranty_years`, `area_m2`, `power_density_w_m2`. Also `manufacturer`, `model`, `cell_technology` text fields.

**Important:** values absent in the retailer's description stay absent; the pipeline does not infer them from titles, marketing claims, or neighboring products. `bifaciality_pct` is the module's reported bifaciality factor (when explicitly given), **not** a predicted energy-production gain. A reported `Pmax` is not proof of actual output in a particular climate.

## Controlled rollout (PowerShell, repo root)

1. Unzip into repository root. Ensure Docker/PostgreSQL and the existing `.env` work as before.
2. Run offline tests:

   ```powershell
   uv run --frozen python -m pytest tests/test_panel_detail_specs.py tests/test_panel_detail_pilot.py -q
   ```

3. Preview synthetic test HTML **without network or database**:

   ```powershell
   uv run --frozen python scripts/panel_detail_pilot.py --html tests/fixtures/panel_detail_ja_solar.html --url "https://sklepsoltech.pl/pl/p/Panel-testowy/4226"
   ```

4. Create only the new table in an **existing** database (the `docker/postgres/init` SQL won't re-run for an existing volume):

   ```powershell
   uv run --frozen python scripts/migrate_panel_specs.py
   ```

5. **Before live collection:** check the retailer's terms and robots rules yourself. If permitted, run a small sample; never use parallel requests or try to bypass an access restriction:

   ```powershell
   # Read up to three AVAILABLE products ranked in the latest Gold snapshot.
   # No database INSERT by default.
   uv run --frozen python scripts/panel_detail_pilot.py --live --limit 3
   ```

   If the first three pages lack data, test a specific product URL:

   ```powershell
   uv run --frozen python scripts/panel_detail_pilot.py --live-url "https://sklepsoltech.pl/pl/p/Panel-fotowoltaiczny-JA-SOLAR-510-JAM60D40-510-LB-BF/4226"
   ```

6. **Review `attributes_raw`, `values`, `parse_issues` and `datasheet_urls`.** If values look correct and no important issues remain, rerun with `--write` to commit captured snapshots in the new table:

   ```powershell
   uv run --frozen python scripts/panel_detail_pilot.py --live --limit 3 --write
   ```

7. Inspect persisted records:

   ```sql
   SELECT spec_id, fetched_at, source_url,
          normalized_values ->> 'model' AS model,
          normalized_values ->> 'rated_power_w' AS power_w,
          normalized_values ->> 'efficiency_pct' AS efficiency_pct,
          normalized_values ->> 'voc_v' AS voc_v,
          normalized_values ->> 'vmp_v' AS vmp_v,
          parse_issues
   FROM bronze.panel_spec_snapshots
   ORDER BY fetched_at DESC, spec_id DESC LIMIT 10;
   ```

8. Re-run `local_release_check.py` and full pytest. Do not change the main Airflow DAG or the existing dashboard yet.

## Product HTML handling

The parser first tries known semantic description containers. If none is available, it looks for a heading such as `Dane techniczne` or `Specyfikacja techniczna`, then parses the following sibling nodes until the next heading. This protects against accidentally parsing recommended products or footer text, but still needs a manual reality check when site DOM changes.

It accepts HTML tables (`th`/`td`), definition lists (`dt`/`dd`) and short text/strong-label paragraphs. Numeric values are parsed only when expected units are explicit. A sample with missing technical information remains incomplete rather than being invented.

The live pilot limits requests to max 5 pages, sequentially, with at least 3 seconds between pages, no retries or access-control bypass. It refuses other domains and unexpected redirects. Any denied request must stop the pilot. The pilot does not download linked PDF documents.

## Data quality

Samples may report: `no_technical_rows`, `no_normalized_values`, `out_of_range_*`, `conflicting_*`, `voc_not_above_vmp`, `isc_below_imp`, `pmax_vs_vmp_imp_mismatch`, `efficiency_vs_area_power_mismatch`, `combined_warranty_needs_review`. These are signals to investigate, not corrections applied to historical observations.

Unknown fields remain accessible in `attributes_raw` to improve the parser later. Multiple variants of the same model should be reviewed carefully; retailer URL still represents the product ID for now.

## Next step (11.2)

After a live sample is reviewed: implement a typed dbt Silver `stg_panel_specifications` model with provenance, tests on electrical and physical quantities, and a Gold enrichment view joined to latest offers by URL. Then expand dashboard filters/technical comparisons. Only after coverage and errors are measured should we schedule a small, rate-limited background enrichment task. Later can extend to inverters and batteries with separate category-specific schemas.
