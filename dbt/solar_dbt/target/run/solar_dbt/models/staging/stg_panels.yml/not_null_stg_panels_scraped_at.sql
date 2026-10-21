
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select scraped_at
from "solar_prices"."silver"."stg_panels"
where scraped_at is null



  
  
      
    ) dbt_internal_test