-- Grain: one row per observation_date.
-- Each product contributes at most once per day.
-- Use latest observation of a product that day BEFORE availability filtering.
WITH ranked AS (
    SELECT
        observed_at::date AS observation_date,
        source_url,
        price_pln,
        power_w,
        pln_per_watt,
        is_available,
        ROW_NUMBER() OVER (
            PARTITION BY observed_at::date, source_url
            ORDER BY observed_at DESC, scrape_id DESC
        ) AS row_of_day
    FROM "solar_prices"."gold"."product_price_history"
),
daily_snapshot AS (
    SELECT *
    FROM ranked
    WHERE row_of_day = 1
),
available AS (
    SELECT *
    FROM daily_snapshot
    WHERE is_available IS TRUE
)
SELECT
    observation_date,
    COUNT(*) AS available_panels,
    ROUND(AVG(price_pln), 2) AS avg_price_pln,
    ROUND(AVG(pln_per_watt), 4) AS avg_pln_per_watt,
    ROUND(MIN(pln_per_watt), 4) AS min_pln_per_watt,
    ROUND(MAX(pln_per_watt), 4) AS max_pln_per_watt
FROM available
GROUP BY observation_date