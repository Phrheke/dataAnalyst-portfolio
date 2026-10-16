-- Singular test: no order may be dated in the future.
--
-- Future-dated rows are a classic symptom of a timezone bug or a bad manual
-- backfill, and they quietly corrupt any "last 30 days" metric. Cheap to check,
-- expensive to discover in a board meeting.

select order_id, order_ts
from {{ ref('stg_orders') }}
where order_ts > current_localtimestamp()
