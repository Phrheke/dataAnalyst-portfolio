select
    cast(product_id as bigint)              as product_id,
    trim(product_name)                      as product_name,
    trim(category)                          as category,
    cast(unit_cost as decimal(14, 2))       as unit_cost,
    cast(list_price as decimal(14, 2))      as list_price
from {{ source('raw', 'products') }}
