ALTER TABLE bronze.panel_scrape_raw
ADD COLUMN IF NOT EXISTS scrape_run_id UUID;