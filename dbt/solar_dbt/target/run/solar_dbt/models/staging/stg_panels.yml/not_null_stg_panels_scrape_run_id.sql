
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    



select scrape_run_id
from "solar_prices"."silver"."stg_panels"
where scrape_run_id is null



  
  
      
    ) dbt_internal_test