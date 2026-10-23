
    
    

select
    observation_date as unique_field,
    count(*) as n_records

from "solar_prices"."gold"."daily_market_prices"
where observation_date is not null
group by observation_date
having count(*) > 1


