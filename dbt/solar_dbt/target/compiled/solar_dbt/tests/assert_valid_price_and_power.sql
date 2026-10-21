SELECT
    scrape_id,
    scrape_run_id,
    title,
    price_pln,
    power_w
FROM "solar_prices"."silver"."stg_panels"
WHERE price_pln IS NULL
   OR price_pln <= 0
   OR power_w IS NULL
   OR power_w <= 0