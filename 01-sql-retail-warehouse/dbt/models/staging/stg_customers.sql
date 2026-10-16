-- Emails are normalised before anything joins on them: the raw table has the
-- same person as "USER@x.com" and "  user@x.com ".
with source as (
    select * from {{ source('raw', 'customers') }}
)

select
    cast(customer_id as bigint)                         as customer_id,
    lower(trim(email))                                  as email,
    cast(signup_date as date)                           as signup_date,
    date_trunc('month', cast(signup_date as date))      as signup_month,
    nullif(trim(country), '')                           as country,
    coalesce(nullif(trim(country), ''), 'unknown')      as country_filled,
    trim(acquisition_channel)                           as acquisition_channel,
    lower(trim(email)) like '%@test.internal'           as is_test_account
from source
