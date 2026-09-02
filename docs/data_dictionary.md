# Data Dictionary

## Overview & Architecture

This document defines the schema, data types, and business definitions across data storage layers, following the Medallion Architecture (Bronze -> Silver -> Gold).

---

## Bronze Layer

### Table: `bronze.panel_scrape_raw`

* **Description:** Raw, append-only landing table capturing unmodified product payloads scraped from the e-commerce source. Serves as the immutable source of truth for downstream transformations.
* **Granularity:** One record per scraped product per scraping run.
* **Ingestion Pattern:** Append-only batch load.

Column,Type,Description & Example
scrape_id,BIGSERIAL,"PK, auto-incrementing surrogate identifier."
scrape_run_id,UUID,Execution batch identifier (audit trail).
title,TEXT,Raw product title.e.g. Panel fotowoltaiczny Jinko 450W
price_text,TEXT,"Unparsed price string from DOM.e.g. 459,00 zł"
power_text,TEXT,Raw power rating before regex cleanup.e.g. 450 W
efficiency_text,TEXT,Raw efficiency string.e.g. 20.65 %
bifaciality_text,TEXT,Raw bifacial indicator.e.g. Bifacial / Dwustronny
source_url,TEXT,Canonical product detail page URL.
is_available,BOOLEAN,"Stock flag (true, false, or NULL if unknown)."
scraped_at,TIMESTAMPTZ,Timestamp of extraction in UTC.

---

## Design Principles (Bronze Layer)

1. **Schema-on-Write for Metadata, Raw Capture for Payload:** Audit attributes (`scrape_id`, `scrape_run_id`, `scraped_at`) are strongly typed, while business fields remain as `TEXT` to prevent parser failures on unexpected DOM changes.
2. **Immutability:** Records in this table are never updated or deleted. Historical changes are tracked by repeated scrapes identifiable via `scrape_run_id` and `scraped_at`.
3. **Downstream Dependencies:** Cleaning, regex extraction of numeric values (e.g., parsing `459,00 zł` to `NUMERIC(10, 2)`), and deduplication occur in the **Silver** layer.