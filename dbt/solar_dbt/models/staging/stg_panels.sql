WITH source_data AS (
    SELECT
        p.scrape_id,
        p.scrape_run_id,
        p.title,
        p.price_text,
        p.power_text,
        p.efficiency_text,
        p.bifaciality_text,
        p.source_url,
        p.is_available,
        p.scraped_at
    FROM {{ source('solar_bronze', 'panel_scrape_raw') }} p
    INNER JOIN {{ source('solar_bronze', 'scrape_runs') }} r
        ON p.scrape_run_id = r.scrape_run_id
    WHERE r.status = 'SUCCESS'
)

SELECT
    scrape_id,
    scrape_run_id,
    title,

    CASE
        WHEN TRIM(price_text) ~ '^[0-9]+([.,][0-9]{1,2})?$'
        THEN REPLACE(TRIM(price_text), ',', '.')::NUMERIC(12,2)
        ELSE NULL
    END AS price_pln,

    CASE
        WHEN TRIM(power_text) ~ '^[0-9]+[[:space:]]*[Ww]?$'
        THEN SUBSTRING(power_text FROM '[0-9]+')::INTEGER
        ELSE NULL
    END AS power_w,

    NULLIF(TRIM(source_url), '') AS source_url,
    is_available,
    scraped_at

FROM source_data
