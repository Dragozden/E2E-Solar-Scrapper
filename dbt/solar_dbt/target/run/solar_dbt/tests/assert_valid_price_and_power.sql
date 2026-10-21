
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
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
  
  
      
    ) dbt_internal_test