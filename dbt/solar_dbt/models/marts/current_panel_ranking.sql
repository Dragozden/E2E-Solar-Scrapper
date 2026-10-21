WITH latest_run AS (
    SELECT scrape_run_id
    FROM {{ source('solar_bronze', 'scrape_runs') }}
    WHERE status = 'SUCCESS'
    ORDER BY finished_at DESC NULLS LAST
    LIMIT 1
),

latest_panels AS (
    SELECT p.*
    FROM {{ ref('stg_panels') }} p
    INNER JOIN latest_run r
        ON p.scrape_run_id = r.scrape_run_id
    WHERE p.price_pln > 0
      AND p.power_w > 0
      AND p.source_url IS NOT NULL
),

deduplicated AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY source_url
            ORDER BY scraped_at DESC, scrape_id DESC
        ) AS product_row
    FROM latest_panels
),

metrics AS (
    SELECT
        scrape_id,
        scrape_run_id,
        title,
        source_url,
        price_pln,
        power_w,
        is_available,
        scraped_at,

        ROUND(
            price_pln / power_w, 4
        ) AS pln_per_watt,

        ROUND(
            power_w / price_pln, 4
        ) AS watt_per_pln,

        CASE
            WHEN price_pln < 200 THEN '<200 zł'
            WHEN price_pln < 300 THEN '200-300 zł'
            WHEN price_pln < 400 THEN '300-400 zł'
            ELSE '400+ zł'
        END AS price_category

    FROM deduplicated
    WHERE product_row = 1
)

SELECT
    ROW_NUMBER() OVER (
        ORDER BY
            CASE WHEN is_available THEN 0 ELSE 1 END,
            pln_per_watt ASC,
            title ASC
    ) AS overall_rank,

    *
FROM metrics
