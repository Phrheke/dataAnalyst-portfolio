-- Two things happen here that cannot be skipped:
--   1. order_ts is parsed with two format attempts. A single cast silently
--      nulls 2% of rows, which deletes real revenue unevenly across weeks.
--   2. The eight status spellings collapse to four states, and the decision
--      about which ones count as revenue is made once, here, via the
--      recognised_statuses project variable.
with source as (
    select * from {{ source('raw', 'orders') }}
),

parsed as (
    select
        cast(order_id as bigint)        as order_id,
        cast(customer_id as bigint)     as customer_id,
        coalesce(
            try_cast(order_ts as timestamp),
            try_strptime(order_ts, '%d/%m/%Y %H:%M')
        )                                as order_ts,
        lower(trim(status))              as status,
        trim(channel)                    as order_channel,
        nullif(trim(discount_code), '')  as discount_code
    from source
)

select
    order_id,
    customer_id,
    order_ts,
    cast(order_ts as date)                          as order_date,
    date_trunc('month', cast(order_ts as date))     as order_month,
    status,
    status in ({{ "'" ~ var('recognised_statuses') | join("', '") ~ "'" }})
                                                    as revenue_recognised,
    order_channel,
    discount_code,
    discount_code is not null                       as used_discount
from parsed
