{{ config(materialized = 'view') }}

-- The single place exclusions are applied. Every analysis model reads this, so
-- two models cannot disagree about revenue because one of them forgot to drop
-- test accounts.
select *
from {{ ref('fct_orders') }}
where revenue_recognised
  and not is_test_account
  and not is_orphan_order
  and order_ts is not null
