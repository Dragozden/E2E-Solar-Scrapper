
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select scrape_run_id
from "solar_prices"."gold"."product_price_history"
where scrape_run_id is null



  
  
      
    ) dbt_internal_test