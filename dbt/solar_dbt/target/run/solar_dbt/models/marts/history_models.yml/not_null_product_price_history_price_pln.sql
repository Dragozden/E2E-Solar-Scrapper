
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select price_pln
from "solar_prices"."gold"."product_price_history"
where price_pln is null



  
  
      
    ) dbt_internal_test