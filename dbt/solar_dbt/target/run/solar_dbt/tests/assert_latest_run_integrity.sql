
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  WITH latest_run AS (
    SELECT
        scrape_run_id,
        products_count
    FROM "solar_prices"."bronze"."scrape_runs"
    WHERE status = 'SUCCESS'
    ORDER BY finished_at DESC NULLS LAST
    LIMIT 1
),

run_quality AS (
    SELECT
        r.scrape_run_id,
        r.products_count AS expected_count,
        COUNT(p.scrape_id) AS actual_count,

        COUNT(p.scrape_id) FILTER (
            WHERE p.source_url IS NULL
               OR TRIM(p.source_url) = ''
        ) AS missing_urls,

        COUNT(p.scrape_id)
            - COUNT(DISTINCT NULLIF(TRIM(p.source_url), ''))
            AS non_unique_urls

    FROM latest_run r
    LEFT JOIN "solar_prices"."bronze"."panel_scrape_raw" p
        ON r.scrape_run_id = p.scrape_run_id
    GROUP BY
        r.scrape_run_id,
        r.products_count
)

SELECT *
FROM run_quality
WHERE actual_count = 0
   OR expected_count IS NULL
   OR actual_count <> expected_count
   OR missing_urls > 0
   OR non_unique_urls > 0
  
  
      
    ) dbt_internal_test