
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select source_url
from "solar_prices"."gold"."product_price_history"
where source_url is null



  
  
      
    ) dbt_internal_test