CREATE TABLE IF NOT EXISTS bronze.panel_scrape_raw (
    scrape_id BIGSERIAL PRIMARY KEY,
    title TEXT,
    price_text TEXT,
    power_text TEXT,
    efficiency_text TEXT,
    bifaciality_text TEXT,
    source_url TEXT,
    scraped_at TIMESTAMP NOT NULL DEFAULT NOW()
);
