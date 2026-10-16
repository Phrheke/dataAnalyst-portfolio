{{ config(materialized = 'table') }}

select
    c.customer_id,
    c.email,
    c.signup_date,
    c.signup_month,
    c.country_filled,
    c.acquisition_channel,
    count(o.order_id)                                       as orders_count,
    coalesce(sum(o.net_revenue), 0)                         as lifetime_revenue,
    min(o.order_date)                                       as first_order_date,
    max(o.order_date)                                       as last_order_date,
    date_diff('day', min(o.order_date), max(o.order_date))  as active_span_days
from {{ ref('stg_customers') }} c
left join {{ ref('analysis_orders') }} o using (customer_id)
where not c.is_test_account
group by all
