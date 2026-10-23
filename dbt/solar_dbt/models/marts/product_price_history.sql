-- Grain: one observation per (scrape_run_id, source_url).
-- Historical prices from successful and completed scrape runs.
WITH observations AS (
    SELECT
        p.scrape_id,
        p.scrape_run_id,
        p.title,
        p.source_url,
        p.price_pln,
        p.power_w,
        p.is_available,
        p.scraped_at,
        r.finished_at AS observed_at
    FROM {{ ref('stg_panels') }} p
    INNER JOIN {{ source('solar_bronze', 'scrape_runs') }} r
      ON p.scrape_run_id = r.scrape_run_id
    WHERE r.status = 'SUCCESS'
      AND r.finished_at IS NOT NULL
      AND p.source_url IS NOT NULL
      AND TRIM(p.source_url) <> ''
      AND p.price_pln > 0
      AND p.power_w > 0
),
numbered AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY scrape_run_id, source_url
            ORDER BY scraped_at DESC, scrape_id DESC
        ) AS row_in_run
    FROM observations
),
sequenced AS (
    SELECT
        scrape_id, scrape_run_id, title, source_url,
        price_pln, power_w, is_available, scraped_at, observed_at,
        ROUND(price_pln / power_w, 4) AS pln_per_watt,
        LAG(price_pln) OVER (
            PARTITION BY source_url
            ORDER BY observed_at, scrape_id
        ) AS previous_price_pln
    FROM numbered
    WHERE row_in_run = 1
)
SELECT
    *,
    price_pln - previous_price_pln AS price_change_pln,
    ROUND(
        100 * (price_pln - previous_price_pln)
        / NULLIF(previous_price_pln, 0), 2
    ) AS price_change_pct
FROM sequenced
