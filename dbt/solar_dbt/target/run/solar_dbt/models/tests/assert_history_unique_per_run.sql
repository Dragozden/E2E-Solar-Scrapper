
  create view "solar_prices"."silver"."assert_history_unique_per_run__dbt_tmp"
    
    
  as (
    -- This test must return 0 rows.
SELECT scrape_run_id, source_url, COUNT(*) AS occurrences
FROM "solar_prices"."gold"."product_price_history"
GROUP BY scrape_run_id, source_url
HAVING COUNT(*) > 1
  );