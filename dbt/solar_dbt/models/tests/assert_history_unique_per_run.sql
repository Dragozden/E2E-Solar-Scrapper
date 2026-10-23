-- This test must return 0 rows.
SELECT scrape_run_id, source_url, COUNT(*) AS occurrences
FROM {{ ref('product_price_history') }}
GROUP BY scrape_run_id, source_url
HAVING COUNT(*) > 1
