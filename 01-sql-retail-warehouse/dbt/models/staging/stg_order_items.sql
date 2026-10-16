-- De-duplication is deterministic: row_number over a fully specified ordering,
-- not `select distinct`. If the duplicate rows ever stop being byte-identical,
-- this still picks the same row every run instead of whichever one the scan
-- happened to see first.
with deduped as (
    select
        *,
        row_number() over (
            partition by order_item_id
            order by order_id, product_id, quantity, unit_price
        ) as rn
    from {{ source('raw', 'order_items') }}
),

typed as (
    select
        cast(d.order_item_id as bigint)         as order_item_id,
        cast(d.order_id as bigint)              as order_id,
        cast(d.product_id as bigint)            as product_id,
        cast(d.quantity as integer)             as quantity,
        cast(d.unit_price as decimal(14, 2))    as unit_price,
        p.list_price,
        p.category
    from deduped d
    left join {{ ref('stg_products') }} p using (product_id)
    where d.rn = 1
)

select
    order_item_id,
    order_id,
    product_id,
    category,
    quantity,
    unit_price,
    list_price,
    unit_price > list_price * {{ var('price_outlier_multiple') }} as is_price_outlier,
    quantity < 0                                                 as is_return,
    -- Both measures are gated on the same price check. Gating only one of them
    -- produced customers with negative six-figure lifetime revenue.
    case
        when quantity > 0
         and unit_price <= list_price * {{ var('price_outlier_multiple') }}
        then quantity * unit_price else 0
    end                                                          as gross_revenue,
    case
        when quantity < 0
         and unit_price <= list_price * {{ var('price_outlier_multiple') }}
        then abs(quantity) * unit_price else 0
    end                                                          as return_value
from typed
