{{ config(materialized = 'table') }}

-- Cohort size is measured at signup, not at month-0 activity. Using month-0
-- buyers as the denominator inflates every later month, which is the most
-- common way a retention chart ends up lying to a board.
with cohort_sizes as (
    select signup_month, count(*) as cohort_size
    from {{ ref('stg_customers') }}
    where not is_test_account
    group by signup_month
),

activity as (
    select distinct
        c.signup_month,
        o.customer_id,
        date_diff('month', c.signup_month, o.order_month) as months_since_signup
    from {{ ref('analysis_orders') }} o
    join {{ ref('stg_customers') }} c using (customer_id)
    where not c.is_test_account
      and date_diff('month', c.signup_month, o.order_month) >= 0
)

select
    s.signup_month,
    s.cohort_size,
    a.months_since_signup,
    count(distinct a.customer_id)                                   as active_customers,
    round(100.0 * count(distinct a.customer_id) / s.cohort_size, 1) as retention_pct
from cohort_sizes s
join activity a using (signup_month)
group by s.signup_month, s.cohort_size, a.months_since_signup
