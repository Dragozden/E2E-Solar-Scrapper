
    
    select
      count(*) as failures,
      count(*) != 0 as should_warn,
      count(*) != 0 as should_error
    from (
      
    
  
    
    

select
    scrape_id as unique_field,
    count(*) as n_records

from "solar_prices"."silver"."stg_panels"
where scrape_id is not null
group by scrape_id
having count(*) > 1



  
  
      
    ) dbt_internal_test