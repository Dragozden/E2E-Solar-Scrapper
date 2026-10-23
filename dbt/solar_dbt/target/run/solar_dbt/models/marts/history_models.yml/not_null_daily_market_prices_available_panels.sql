
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select available_panels
from "solar_prices"."gold"."daily_market_prices"
where available_panels is null



  
  
      
    ) dbt_internal_test