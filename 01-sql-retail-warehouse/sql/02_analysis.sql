-- =============================================================================
-- 02_analysis.sql — ten business questions.
--
-- Each block states the question in the language a stakeholder would use, the
-- technique it needs, and the finding it produced. The findings are written out
-- in full in 01-sql-retail-warehouse/README.md, and the one-line versions here are
-- so that someone reading the SQL alone still learns something.
--
-- Run:  duckdb warehouse.duckdb < 01-sql-retail-warehouse/sql/02_analysis.sql
-- Requires 01_staging.sql.
-- =============================================================================


-- =============================================================================
-- Q1. "Is revenue growing, and how fast?"
-- Technique: LAG over an ordered window for month-on-month change.
-- Why not a simple GROUP BY: a stakeholder never wants the level without the
-- delta, and computing the delta in the spreadsheet afterwards is how
-- off-by-one-month errors get into board decks.
-- =============================================================================
CREATE OR REPLACE VIEW q1_revenue_trend AS
WITH monthly AS (
    SELECT
        order_month,
        sum(net_revenue)            AS net_revenue,
        count(*)                    AS orders,
        count(DISTINCT customer_id) AS buyers
    FROM analysis_orders
    GROUP BY order_month
)
SELECT
    order_month,
    net_revenue,
    orders,
    buyers,
    net_revenue / orders                                      AS avg_order_value,
    lag(net_revenue) OVER w                                   AS prev_month_revenue,
    round(100.0 * (net_revenue - lag(net_revenue) OVER w)
          / nullif(lag(net_revenue) OVER w, 0), 1)            AS mom_growth_pct,
    -- A 3-month trailing average, because monthly revenue in a business this
    -- size is noisy enough that a single month's dip means nothing.
    round(avg(net_revenue) OVER (ORDER BY order_month
          ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2)       AS revenue_3mo_avg
FROM monthly
WINDOW w AS (ORDER BY order_month)
ORDER BY order_month;


-- =============================================================================
-- Q2. "How much of each month's revenue comes from customers we already had?"
-- Technique: first order date per customer via MIN window, then classify each
-- order as the customer's first or a repeat.
-- Why it matters: a business whose growth is all first-time buyers is renting
-- its revenue from the ad platforms. The split is the single most diagnostic
-- chart in e-commerce.
-- =============================================================================
CREATE OR REPLACE VIEW q2_new_vs_returning AS
WITH tagged AS (
    SELECT
        order_id,
        customer_id,
        order_month,
        net_revenue,
        min(order_month) OVER (PARTITION BY customer_id) AS first_order_month
    FROM analysis_orders
)
SELECT
    order_month,
    coalesce(sum(net_revenue) FILTER (WHERE order_month =  first_order_month), 0) AS new_customer_revenue,
    coalesce(sum(net_revenue) FILTER (WHERE order_month <> first_order_month), 0) AS returning_customer_revenue,
    sum(net_revenue)                                                 AS total_revenue,
    round(100.0 * coalesce(sum(net_revenue) FILTER (WHERE order_month <> first_order_month), 0)
          / nullif(sum(net_revenue), 0), 1)                          AS pct_from_returning
FROM tagged
GROUP BY order_month
ORDER BY order_month;


-- =============================================================================
-- Q3. "Do the customers we acquire stick around?"
-- Technique: monthly cohort retention. Signup month on the rows, months since
-- signup on the columns, share of the cohort still ordering in the cells.
-- This is the query most analyst interviews are secretly asking about.
--
-- The denominator is cohort size measured at signup, not at month 0 activity.
-- Using month-0 buyers as the denominator inflates every later month and is the
-- most common way retention charts lie.
-- =============================================================================
CREATE OR REPLACE VIEW q3_cohort_retention AS
WITH cohort_sizes AS (
    SELECT signup_month, count(*) AS cohort_size
    FROM stg_customers
    WHERE NOT is_test_account
    GROUP BY signup_month
),
activity AS (
    SELECT DISTINCT
        c.signup_month,
        o.customer_id,
        date_diff('month', c.signup_month, o.order_month) AS months_since_signup
    FROM analysis_orders o
    JOIN stg_customers c USING (customer_id)
    WHERE NOT c.is_test_account
      AND date_diff('month', c.signup_month, o.order_month) >= 0
)
SELECT
    s.signup_month,
    s.cohort_size,
    a.months_since_signup,
    count(DISTINCT a.customer_id)                                    AS active_customers,
    round(100.0 * count(DISTINCT a.customer_id) / s.cohort_size, 1)  AS retention_pct
FROM cohort_sizes s
JOIN activity a USING (signup_month)
GROUP BY s.signup_month, s.cohort_size, a.months_since_signup
ORDER BY s.signup_month, a.months_since_signup;

-- The same thing pivoted into the triangle shape a stakeholder expects to see.
-- Months 0-6 only: beyond that the recent cohorts have no data yet and the
-- empty cells invite people to read a trend that is really just censoring.
CREATE OR REPLACE VIEW q3_cohort_retention_pivot AS
SELECT
    signup_month,
    max(cohort_size) AS cohort_size,
    max(retention_pct) FILTER (WHERE months_since_signup = 0) AS m0,
    max(retention_pct) FILTER (WHERE months_since_signup = 1) AS m1,
    max(retention_pct) FILTER (WHERE months_since_signup = 2) AS m2,
    max(retention_pct) FILTER (WHERE months_since_signup = 3) AS m3,
    max(retention_pct) FILTER (WHERE months_since_signup = 4) AS m4,
    max(retention_pct) FILTER (WHERE months_since_signup = 5) AS m5,
    max(retention_pct) FILTER (WHERE months_since_signup = 6) AS m6
FROM q3_cohort_retention
GROUP BY signup_month
ORDER BY signup_month;


-- =============================================================================
-- Q4. "What is a customer worth over time, and does it differ by cohort?"
-- Technique: cumulative SUM over an ordered window, normalised per cohort head.
-- Why cumulative-per-head rather than total: cohort sizes differ by 2.6x across
-- the two years, so raw cumulative revenue compares cohort size, not quality.
-- =============================================================================
CREATE OR REPLACE VIEW q4_ltv_curve AS
WITH per_month AS (
    SELECT
        c.signup_month,
        date_diff('month', c.signup_month, o.order_month) AS months_since_signup,
        sum(o.net_revenue)                                AS revenue
    FROM analysis_orders o
    JOIN stg_customers c USING (customer_id)
    WHERE NOT c.is_test_account
      AND date_diff('month', c.signup_month, o.order_month) BETWEEN 0 AND 11
    GROUP BY 1, 2
),
sizes AS (
    SELECT signup_month, count(*) AS cohort_size
    FROM stg_customers WHERE NOT is_test_account GROUP BY signup_month
)
SELECT
    p.signup_month,
    s.cohort_size,
    p.months_since_signup,
    p.revenue,
    sum(p.revenue) OVER (
        PARTITION BY p.signup_month
        ORDER BY p.months_since_signup
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    )                                                     AS cumulative_revenue,
    round(sum(p.revenue) OVER (
        PARTITION BY p.signup_month
        ORDER BY p.months_since_signup
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) / s.cohort_size, 2)                                 AS cumulative_ltv_per_customer
FROM per_month p
JOIN sizes s USING (signup_month)
ORDER BY p.signup_month, p.months_since_signup;


-- =============================================================================
-- Q5. "Who should the retention team actually email?"
-- Technique: RFM scoring with NTILE(5) on recency, frequency and monetary.
-- Deliberately mapped to named segments, because "RFM 544" is not something a
-- marketing manager can act on but "loyal, slipping away" is.
-- =============================================================================
CREATE OR REPLACE VIEW q5_rfm_segments AS
WITH bounds AS (SELECT max(order_date) AS as_of FROM analysis_orders),
base AS (
    SELECT
        o.customer_id,
        date_diff('day', max(o.order_date), (SELECT as_of FROM bounds)) AS recency_days,
        count(*)                                                        AS frequency,
        sum(o.net_revenue)                                              AS monetary
    FROM analysis_orders o
    GROUP BY o.customer_id
),
scored AS (
    SELECT
        *,
        -- Recency is reversed: fewer days since the last order is better, so
        -- the NTILE is taken on descending recency.
        --
        -- customer_id is a tiebreaker on every one of these, and it is not
        -- cosmetic. NTILE assigns buckets by row position, so when the ORDER BY
        -- is not a total order the engine is free to place tied rows in any
        -- sequence -- and DuckDB's parallel scan genuinely does vary run to run.
        -- Without the tiebreaker, three consecutive runs of this exact query on
        -- this exact data put 1,006 / 1,003 / 1,029 customers in the 'at risk'
        -- segment. A portfolio number that moves when the reader re-runs it is
        -- worse than no number.
        ntile(5) OVER (ORDER BY recency_days DESC, customer_id) AS r_score,
        ntile(5) OVER (ORDER BY frequency ASC, customer_id)     AS f_score,
        ntile(5) OVER (ORDER BY monetary ASC, customer_id)      AS m_score
    FROM base
)
SELECT
    customer_id,
    recency_days,
    frequency,
    monetary,
    r_score, f_score, m_score,
    CASE
        WHEN r_score >= 4 AND f_score >= 4 THEN 'champion'
        WHEN r_score >= 4 AND f_score <= 2 THEN 'promising new'
        WHEN r_score <= 2 AND f_score >= 4 THEN 'at risk - was loyal'
        WHEN r_score <= 2 AND f_score <= 2 THEN 'lapsed'
        WHEN m_score = 5                    THEN 'big spender'
        ELSE 'steady'
    END AS segment
FROM scored;

CREATE OR REPLACE VIEW q5_rfm_summary AS
SELECT
    segment,
    count(*)                        AS customers,
    round(avg(recency_days), 0)     AS avg_days_since_order,
    round(avg(frequency), 2)        AS avg_orders,
    round(avg(monetary), 0)         AS avg_revenue,
    sum(monetary)                   AS segment_revenue,
    round(100.0 * sum(monetary) / sum(sum(monetary)) OVER (), 1) AS pct_of_revenue
FROM q5_rfm_segments
GROUP BY segment
ORDER BY segment_revenue DESC;


-- =============================================================================
-- Q6. "How concentrated is our revenue?"
-- Technique: cumulative share with a window function over ranked customers.
-- Why it matters: it sizes the risk. If the top decile is most of the revenue,
-- a retention problem in that decile is an existential problem.
-- =============================================================================
CREATE OR REPLACE VIEW q6_revenue_concentration AS
WITH ranked AS (
    SELECT
        customer_id,
        lifetime_revenue,
        -- Same tiebreaker rule as Q5: NTILE over a non-total order is
        -- non-deterministic under parallel execution.
        ntile(10) OVER (ORDER BY lifetime_revenue DESC, customer_id) AS revenue_decile
    FROM dim_customers
    WHERE lifetime_revenue > 0
)
SELECT
    revenue_decile,
    count(*)                                 AS customers,
    sum(lifetime_revenue)                    AS decile_revenue,
    round(100.0 * sum(lifetime_revenue) / sum(sum(lifetime_revenue)) OVER (), 1) AS pct_of_revenue,
    round(100.0 * sum(sum(lifetime_revenue)) OVER (ORDER BY revenue_decile)
          / sum(sum(lifetime_revenue)) OVER (), 1)                               AS cumulative_pct
FROM ranked
GROUP BY revenue_decile
ORDER BY revenue_decile;


-- =============================================================================
-- Q7. "How long do people wait between orders?"
-- Technique: LAG partitioned by customer to get the gap between consecutive
-- orders, then percentiles of that gap by order sequence number.
-- Why percentiles: the mean gap is dragged up by a long tail of people who came
-- back after a year, and the median is what a lifecycle email schedule needs.
-- =============================================================================
CREATE OR REPLACE VIEW q7_repeat_interval AS
WITH seq AS (
    SELECT
        customer_id,
        order_date,
        row_number() OVER (PARTITION BY customer_id ORDER BY order_date) AS order_seq,
        lag(order_date) OVER (PARTITION BY customer_id ORDER BY order_date) AS prev_order_date
    FROM analysis_orders
)
SELECT
    order_seq                                          AS nth_order,
    count(*)                                           AS customers_reaching,
    round(avg(date_diff('day', prev_order_date, order_date)), 1) AS mean_gap_days,
    quantile_cont(date_diff('day', prev_order_date, order_date), 0.5)  AS median_gap_days,
    quantile_cont(date_diff('day', prev_order_date, order_date), 0.75) AS p75_gap_days
FROM seq
WHERE prev_order_date IS NOT NULL
  AND order_seq <= 6
GROUP BY order_seq
ORDER BY order_seq;


-- =============================================================================
-- Q8. "Which acquisition channel actually pays for itself?"
-- Technique: join 12-month cohort revenue against marketing spend to get a
-- blended CAC and a payback ratio per channel.
--
-- Caveat stated in the output, not buried: spend is recorded per channel per
-- month with no customer-level attribution, so this is a blended CAC, not a
-- causal one. Treating it as causal is the mistake this query is designed to
-- make visible rather than commit.
-- =============================================================================
CREATE OR REPLACE VIEW q8_channel_payback AS
WITH acquired AS (
    SELECT
        acquisition_channel AS channel,
        signup_month,
        count(*)            AS customers_acquired
    FROM stg_customers
    WHERE NOT is_test_account
    GROUP BY 1, 2
),
cohort_revenue AS (
    SELECT
        c.acquisition_channel AS channel,
        c.signup_month,
        sum(o.net_revenue)    AS revenue_12mo
    FROM analysis_orders o
    JOIN stg_customers c USING (customer_id)
    WHERE NOT c.is_test_account
      AND date_diff('month', c.signup_month, o.order_month) BETWEEN 0 AND 11
    GROUP BY 1, 2
),
spend AS (
    SELECT channel, spend_month AS signup_month, spend_ngn FROM stg_marketing_spend
)
SELECT
    a.channel,
    sum(a.customers_acquired)                                      AS customers,
    sum(coalesce(s.spend_ngn, 0))                                  AS spend,
    sum(coalesce(r.revenue_12mo, 0))                               AS revenue_12mo,
    round(sum(coalesce(s.spend_ngn, 0)) / nullif(sum(a.customers_acquired), 0), 0) AS blended_cac,
    round(sum(coalesce(r.revenue_12mo, 0)) / nullif(sum(a.customers_acquired), 0), 0) AS revenue_per_customer_12mo,
    round(sum(coalesce(r.revenue_12mo, 0)) / nullif(sum(coalesce(s.spend_ngn, 0)), 0), 2) AS revenue_per_naira_spent,
    CASE WHEN sum(coalesce(s.spend_ngn, 0)) = 0
         THEN 'unpaid channel - no spend recorded'
         ELSE 'blended CAC, not causal' END                        AS caveat
FROM acquired a
LEFT JOIN cohort_revenue r USING (channel, signup_month)
LEFT JOIN spend s          USING (channel, signup_month)
GROUP BY a.channel
ORDER BY revenue_per_naira_spent DESC NULLS LAST;


-- =============================================================================
-- Q9. "Where do we lose people, and on what device?"
-- Technique: conversion rates by device and source with a window-computed
-- share of total traffic, so volume and rate are visible in one table.
-- Reading a 4% conversion rate without knowing it is 2% of traffic is how teams
-- end up optimising the segment that cannot move the total.
-- =============================================================================
CREATE OR REPLACE VIEW q9_conversion_by_segment AS
SELECT
    device,
    source,
    count(*)                                                   AS sessions,
    round(100.0 * count(*) / sum(count(*)) OVER (), 1)         AS pct_of_sessions,
    count(*) FILTER (WHERE converted)                          AS conversions,
    round(100.0 * count(*) FILTER (WHERE converted) / count(*), 2) AS conversion_rate_pct,
    round(avg(pages_viewed), 2)                                AS avg_pages,
    -- Lift against the overall rate makes the table scannable: a reader looks
    -- for the negative numbers instead of doing arithmetic in their head.
    round(100.0 * count(*) FILTER (WHERE converted) / count(*)
          - (SELECT 100.0 * count(*) FILTER (WHERE converted) / count(*) FROM stg_sessions), 2)
                                                               AS pp_vs_overall
FROM stg_sessions
GROUP BY device, source
HAVING count(*) >= 200   -- suppress cells too small to read a rate from
ORDER BY sessions DESC;


-- =============================================================================
-- Q10. "What gets bought together?"
-- Technique: self-join on order_id to build category pairs, with support and
-- lift. a.category < b.category dedupes the mirrored pairs.
-- Lift > 1 means the pair co-occurs more than independence would predict, which
-- is the number a merchandiser can act on. Raw co-occurrence counts just rank
-- the popular categories against each other.
-- =============================================================================
CREATE OR REPLACE VIEW q10_category_affinity AS
WITH order_categories AS (
    SELECT DISTINCT i.order_id, i.category
    FROM stg_order_items i
    JOIN analysis_orders o USING (order_id)
    WHERE i.category IS NOT NULL
      AND NOT i.is_return
),
total_orders AS (SELECT count(DISTINCT order_id) AS n FROM order_categories),
single AS (
    SELECT category, count(DISTINCT order_id) AS orders_with
    FROM order_categories GROUP BY category
),
pairs AS (
    SELECT a.category AS cat_a, b.category AS cat_b, count(*) AS orders_with_both
    FROM order_categories a
    JOIN order_categories b
      ON a.order_id = b.order_id
     AND a.category < b.category
    GROUP BY 1, 2
)
SELECT
    p.cat_a,
    p.cat_b,
    p.orders_with_both,
    round(100.0 * p.orders_with_both / t.n, 2)                        AS support_pct,
    round(1.0 * p.orders_with_both / sa.orders_with * 100, 1)         AS pct_of_cat_a_orders,
    round(
        (1.0 * p.orders_with_both / t.n) /
        ((1.0 * sa.orders_with / t.n) * (1.0 * sb.orders_with / t.n))
    , 2)                                                              AS lift
FROM pairs p
CROSS JOIN total_orders t
JOIN single sa ON sa.category = p.cat_a
JOIN single sb ON sb.category = p.cat_b
WHERE p.orders_with_both >= 30
ORDER BY lift DESC;
