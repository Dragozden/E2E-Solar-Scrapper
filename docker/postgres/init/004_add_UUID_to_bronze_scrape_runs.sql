CREATE TABLE IF NOT EXISTS bronze.scrape_runs (
    scrape_run_id UUID PRIMARY KEY,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status TEXT NOT NULL,
    products_count INTEGER
);