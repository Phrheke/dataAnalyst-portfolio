select
    cast(spend_month as date)           as spend_month,
    trim(channel)                       as channel,
    cast(spend_ngn as decimal(16, 2))   as spend_ngn
from {{ source('raw', 'marketing_spend') }}
