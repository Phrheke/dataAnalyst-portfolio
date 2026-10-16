-- Singular test: order-level revenue must equal the sum of its line items.
--
-- This is the test that catches a fan-out. If someone later changes fct_orders
-- to join items without pre-aggregating, order revenue silently multiplies and
-- every number in every dashboard moves. A uniqueness test on order_id would
-- NOT catch it, because the join could still produce one row per order while
-- the revenue column is wrong.
--
-- Tolerance of 0.01 absorbs decimal rounding, nothing more.

with order_level as (
    select order_id, gross_revenue
    from {{ ref('fct_orders') }}
),

item_level as (
    select order_id, sum(gross_revenue) as gross_revenue
    from {{ ref('stg_order_items') }}
    group by order_id
)

select
    o.order_id,
    o.gross_revenue   as fct_revenue,
    i.gross_revenue   as item_revenue,
    abs(o.gross_revenue - coalesce(i.gross_revenue, 0)) as difference
from order_level o
left join item_level i using (order_id)
where abs(o.gross_revenue - coalesce(i.gross_revenue, 0)) > 0.01
