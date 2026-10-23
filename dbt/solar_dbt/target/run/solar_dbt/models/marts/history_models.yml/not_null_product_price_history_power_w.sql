
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select power_w
from "solar_prices"."gold"."product_price_history"
where power_w is null



  
  
      
    ) dbt_internal_test