-- =============================================================================
-- churn_features.sql — build the modelling table.
--
-- The hard part of a churn model is not the model. It is drawing the line
-- between "what we knew then" and "what happened next" without letting the
-- second leak into the first. Everything here is organised around that line.
--
--   observation cutoff  = the last order date in the data, minus 90 days
--   feature window      = everything strictly BEFORE the cutoff
--   label window        = the 90 days AFTER the cutoff
--   churned             = 1 if the customer placed no order in the label window
--
-- Eligibility: the customer must have ordered at least once in the **180 days
-- before the cutoff**, and must have signed up at least 90 days before it.
--
-- That first condition is the whole ballgame. The obvious alternative -- "anyone
-- who ever ordered" -- scores 99% churned, because a base accumulated over two
-- years is mostly people who left long ago. A model trained on that learns
-- "almost everyone churns" and is right 99% of the time while being useless.
-- The business question is not "has this customer ever lapsed"; it is "of the
-- customers active today, which ones will go quiet", and that is what the
-- active-base definition asks.
--
-- Requires 01-sql-retail-warehouse/sql/01_staging.sql.
-- =============================================================================

-- {{CUTOFF_OFFSET_DAYS}} is substituted by churn_model.py so the same
-- definition can build an earlier snapshot for out-of-time validation. It
-- defaults to 90, so the file still runs unmodified in a SQL client.
CREATE OR REPLACE VIEW churn_config AS
SELECT
    max(order_date)                                              AS data_end,
    max(order_date) - INTERVAL {{CUTOFF_OFFSET_DAYS}} DAY        AS cutoff,
    90                                       AS label_days,
    90                                       AS min_tenure_days,
    180                                      AS active_window_days
FROM analysis_orders;

CREATE OR REPLACE VIEW churn_features AS
WITH cfg AS (SELECT * FROM churn_config),

-- Only orders strictly before the cutoff may inform a feature.
hist AS (
    SELECT o.*
    FROM analysis_orders o
    CROSS JOIN cfg
    WHERE o.order_date < CAST(cfg.cutoff AS DATE)
),

eligible AS (
    SELECT c.customer_id, c.signup_date, c.signup_month,
           c.country_filled, c.acquisition_channel
    FROM stg_customers c
    CROSS JOIN cfg
    WHERE NOT c.is_test_account
      AND c.signup_date <= CAST(cfg.cutoff AS DATE) - cfg.min_tenure_days
      -- Active base: ordered at least once in the 180 days before the cutoff.
      AND EXISTS (
          SELECT 1 FROM hist h
          WHERE h.customer_id = c.customer_id
            AND h.order_date >= CAST(cfg.cutoff AS DATE) - cfg.active_window_days
      )
),

order_features AS (
    SELECT
        h.customer_id,
        count(*)                                                   AS orders_total,
        sum(h.net_revenue)                                         AS revenue_total,
        avg(h.net_revenue)                                          AS avg_order_value,
        max(h.order_date)                                          AS last_order_date,
        min(h.order_date)                                          AS first_order_date,
        count(*) FILTER (WHERE h.used_discount)                    AS discounted_orders,
        count(DISTINCT h.order_month)                              AS active_months,
        -- Momentum: orders in the 90 days before the cutoff versus the 90
        -- before that. A customer slowing down is the signal; a customer with
        -- a high lifetime count who has stopped is the expensive kind of churn.
        count(*) FILTER (
            WHERE h.order_date >= (SELECT CAST(cutoff AS DATE) FROM cfg) - 90
        )                                                          AS orders_last_90d,
        count(*) FILTER (
            WHERE h.order_date >= (SELECT CAST(cutoff AS DATE) FROM cfg) - 180
              AND h.order_date <  (SELECT CAST(cutoff AS DATE) FROM cfg) - 90
        )                                                          AS orders_prev_90d,
        sum(h.return_value) > 0                                    AS has_returned
    FROM hist h
    GROUP BY h.customer_id
),

-- Median gap between consecutive orders: a two-order customer with a 7 day gap
-- behaves nothing like a two-order customer with a 200 day gap.
gaps AS (
    SELECT
        customer_id,
        quantile_cont(gap_days, 0.5) AS median_gap_days,
        max(gap_days)                AS max_gap_days
    FROM (
        SELECT
            customer_id,
            date_diff('day',
                lag(order_date) OVER (PARTITION BY customer_id ORDER BY order_date),
                order_date) AS gap_days
        FROM hist
    ) g
    WHERE gap_days IS NOT NULL
    GROUP BY customer_id
),

category_features AS (
    SELECT
        h.customer_id,
        count(DISTINCT i.category)                                      AS distinct_categories,
        count(*) FILTER (WHERE i.category = 'bundles')                  AS bundle_items,
        count(*) FILTER (WHERE i.category = 'skincare')                 AS skincare_items
    FROM hist h
    JOIN stg_order_items i USING (order_id)
    WHERE NOT i.is_return
    GROUP BY h.customer_id
),

session_features AS (
    SELECT
        s.customer_id,
        count(*)                                                        AS sessions_total,
        avg(s.pages_viewed)                                             AS avg_pages_viewed,
        100.0 * count(*) FILTER (WHERE s.device = 'mobile') / count(*)  AS pct_mobile_sessions,
        count(*) FILTER (
            WHERE s.session_date >= (SELECT CAST(cutoff AS DATE) FROM cfg) - 90
        )                                                               AS sessions_last_90d
    FROM stg_sessions s
    CROSS JOIN cfg
    WHERE s.session_date < CAST(cfg.cutoff AS DATE)
    GROUP BY s.customer_id
),

-- The label. Strictly after the cutoff, and never joined into the feature CTEs.
labels AS (
    SELECT
        e.customer_id,
        CASE WHEN EXISTS (
            SELECT 1 FROM analysis_orders o
            CROSS JOIN cfg
            WHERE o.customer_id = e.customer_id
              AND o.order_date >= CAST(cfg.cutoff AS DATE)
              -- Upper bound matters. Without it the label window runs to the
              -- end of the data, which is correct only when the cutoff happens
              -- to sit exactly label_days from the end. For an earlier snapshot
              -- it would quietly become a much longer window, making the
              -- training labels incomparable to the test labels.
              AND o.order_date <  CAST(cfg.cutoff AS DATE) + cfg.label_days
        ) THEN 0 ELSE 1 END AS churned
    FROM eligible e
)

SELECT
    e.customer_id,
    -- Target
    l.churned,
    -- Recency and tenure, measured at the cutoff
    date_diff('day', o.last_order_date, (SELECT CAST(cutoff AS DATE) FROM cfg)) AS days_since_last_order,
    date_diff('day', e.signup_date,     (SELECT CAST(cutoff AS DATE) FROM cfg)) AS tenure_days,
    date_diff('day', o.first_order_date, o.last_order_date)                     AS active_span_days,
    -- Volume and value
    o.orders_total,
    o.revenue_total,
    o.avg_order_value,
    o.active_months,
    -- Momentum
    o.orders_last_90d,
    o.orders_prev_90d,
    o.orders_last_90d - o.orders_prev_90d                                       AS order_momentum,
    -- Cadence
    coalesce(g.median_gap_days, 0)                                              AS median_gap_days,
    coalesce(g.max_gap_days, 0)                                                 AS max_gap_days,
    -- A customer is "overdue" if their silence already exceeds their own
    -- normal rhythm. This ratio is far more informative than raw recency,
    -- because it is scaled to the individual.
    CASE WHEN coalesce(g.median_gap_days, 0) > 0
         THEN date_diff('day', o.last_order_date, (SELECT CAST(cutoff AS DATE) FROM cfg))
              / g.median_gap_days
         ELSE NULL END                                                          AS overdue_ratio,
    -- Behaviour
    100.0 * o.discounted_orders / o.orders_total                                AS pct_discounted,
    o.has_returned,
    coalesce(c.distinct_categories, 0)                                          AS distinct_categories,
    coalesce(c.bundle_items, 0)                                                 AS bundle_items,
    coalesce(s.sessions_total, 0)                                               AS sessions_total,
    coalesce(s.sessions_last_90d, 0)                                            AS sessions_last_90d,
    coalesce(s.avg_pages_viewed, 0)                                             AS avg_pages_viewed,
    coalesce(s.pct_mobile_sessions, 0)                                          AS pct_mobile_sessions,
    -- Categoricals, one-hot encoded in Python rather than here
    e.acquisition_channel,
    e.country_filled
FROM eligible e
JOIN labels l          USING (customer_id)
JOIN order_features o  USING (customer_id)
LEFT JOIN gaps g       USING (customer_id)
LEFT JOIN category_features c USING (customer_id)
LEFT JOIN session_features s  USING (customer_id);
