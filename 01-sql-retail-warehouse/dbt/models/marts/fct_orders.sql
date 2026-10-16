{{ config(materialized = 'table') }}

-- One row per order. Items are pre-aggregated to order grain here so that
-- nothing downstream joins orders to items and accidentally multiplies an
-- order-level column by its line count.
with items as (
    select
        order_id,
        count(*)            as n_items,
        sum(gross_revenue)  as gross_revenue,
        sum(return_value)   as return_value
    from {{ ref('stg_order_items') }}
    group by order_id
)

select
    o.order_id,
    o.customer_id,
    o.order_ts,
    o.order_date,
    o.order_month,
    o.status,
    o.revenue_recognised,
    o.order_channel,
    o.used_discount,
    -- Orphans are flagged, not dropped. An inner join here would silently
    -- delete the revenue of customers deleted upstream for GDPR requests.
    c.customer_id is null                   as is_orphan_order,
    c.signup_month,
    c.acquisition_channel,
    c.country_filled,
    coalesce(c.is_test_account, false)      as is_test_account,
    coalesce(i.n_items, 0)                  as n_items,
    coalesce(i.gross_revenue, 0)            as gross_revenue,
    coalesce(i.return_value, 0)             as return_value,
    coalesce(i.gross_revenue, 0) - coalesce(i.return_value, 0) as net_revenue
from {{ ref('stg_orders') }} o
left join {{ ref('stg_customers') }} c using (customer_id)
left join items i using (order_id)
