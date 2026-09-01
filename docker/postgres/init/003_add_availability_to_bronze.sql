ALTER TABLE bronze.panel_scrape_raw
ADD COLUMN IF NOT EXISTS is_available BOOLEAN;