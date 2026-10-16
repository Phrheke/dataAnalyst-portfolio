select
    cast(session_id as bigint)                          as session_id,
    cast(customer_id as bigint)                         as customer_id,
    cast(session_date as date)                          as session_date,
    date_trunc('month', cast(session_date as date))     as session_month,
    trim(device)                                        as device,
    trim(source)                                        as source,
    cast(pages_viewed as integer)                       as pages_viewed,
    cast(converted as integer) = 1                      as converted
from {{ source('raw', 'sessions') }}
