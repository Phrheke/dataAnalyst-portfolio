-- =============================================================================
-- dashboard_mart.sql — the views behind the retention dashboard.
--
-- A dashboard mart is not "the analysis queries, exported". It is a deliberately
-- small, deliberately shaped set of tables answering ONE stakeholder's ONE
-- recurring question. Everything here is driven by the decision documented in
-- spec/SPEC.md: where does the retention lead spend next month's budget.
--
-- Three rules this file follows:
--   1. One row per thing the dashboard draws. No post-processing in the BI tool,
--      because logic that lives in a Tableau calculated field is invisible to
--      code review and impossible to test.
--   2. Censored cohorts are excluded explicitly, not left for the reader to
--      notice. A cohort triangle with six half-empty rows invites people to
--      read a trend that is really just missing data.
--   3. Every percentage arrives pre-computed with its denominator declared, so
--      no one can average a set of averages.
--
-- Requires 01-sql-retail-warehouse/sql/01_staging.sql and 02_analysis.sql.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- dash_kpi — the four numbers at the top. One row.
--
-- "Last complete month" matters: the current month is always partial and always
-- looks like a collapse. Showing it next to complete months is the single most
-- common way a dashboard causes a false alarm.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW dash_kpi AS
WITH bounds AS (
    SELECT date_trunc('month', max(order_date)) AS partial_month
    FROM analysis_orders
),
last_complete AS (
    SELECT (SELECT partial_month FROM bounds) - INTERVAL 1 MONTH AS m
),
rev AS (
    SELECT
        sum(net_revenue) FILTER (WHERE order_month = (SELECT m FROM last_complete))          AS revenue_last_month,
        sum(net_revenue) FILTER (WHERE order_month = (SELECT m FROM last_complete) - INTERVAL 1 MONTH) AS revenue_prev_month,
        count(DISTINCT customer_id) FILTER (WHERE order_month = (SELECT m FROM last_complete)) AS buyers_last_month
    FROM analysis_orders
),
repeat_share AS (
    SELECT pct_from_returning
    FROM q2_new_vs_returning
    WHERE order_month = (SELECT m FROM last_complete)
),
-- Month-1 retention for the most recent cohort that has a full month 1.
latest_m1 AS (
    SELECT retention_pct, signup_month
    FROM q3_cohort_retention
    WHERE months_since_signup = 1
    ORDER BY signup_month DESC
    LIMIT 1
),
at_risk AS (
    SELECT customers, segment_revenue, pct_of_revenue
    FROM q5_rfm_summary
    WHERE segment = 'at risk - was loyal'
)
SELECT
    (SELECT m FROM last_complete)                       AS as_of_month,
    r.revenue_last_month,
    r.revenue_prev_month,
    round(100.0 * (r.revenue_last_month - r.revenue_prev_month)
          / nullif(r.revenue_prev_month, 0), 1)         AS revenue_mom_pct,
    r.buyers_last_month,
    rs.pct_from_returning                                AS repeat_revenue_share_pct,
    m1.retention_pct                                     AS latest_month1_retention_pct,
    m1.signup_month                                      AS latest_m1_cohort,
    ar.customers                                         AS at_risk_customers,
    ar.segment_revenue                                   AS at_risk_revenue,
    ar.pct_of_revenue                                    AS at_risk_pct_of_revenue
FROM rev r
CROSS JOIN repeat_share rs
CROSS JOIN latest_m1 m1
CROSS JOIN at_risk ar;

-- -----------------------------------------------------------------------------
-- dash_revenue_split — monthly revenue, split new versus returning.
-- The partial final month is dropped, for the reason in dash_kpi.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW dash_revenue_split AS
SELECT
    order_month,
    new_customer_revenue,
    returning_customer_revenue,
    total_revenue,
    pct_from_returning
FROM q2_new_vs_returning
WHERE order_month < (SELECT date_trunc('month', max(order_date)) FROM analysis_orders)
ORDER BY order_month;

-- -----------------------------------------------------------------------------
-- dash_cohort_heatmap — the triangle, with censored cells removed.
--
-- A cohort is only shown for month N if the whole cohort has had N months to
-- act. Anything else is a cell that looks like churn but is really the calendar.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW dash_cohort_heatmap AS
WITH data_end AS (SELECT max(order_month) AS m FROM analysis_orders)
SELECT
    r.signup_month,
    r.cohort_size,
    r.months_since_signup,
    r.active_customers,
    r.retention_pct
FROM q3_cohort_retention r
CROSS JOIN data_end d
WHERE r.months_since_signup <= date_diff('month', r.signup_month, d.m)
  AND r.months_since_signup <= 11
ORDER BY r.signup_month, r.months_since_signup;

-- -----------------------------------------------------------------------------
-- dash_retention_curve — the average curve over cohorts with complete history.
--
-- Averaged across only those cohorts old enough to have every month in the
-- range, so each point on the line is computed over the same set of cohorts.
-- Averaging over whatever happens to be available makes the curve bend upward
-- at the tail for purely compositional reasons.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW dash_retention_curve AS
WITH complete_cohorts AS (
    SELECT signup_month
    FROM q3_cohort_retention
    GROUP BY signup_month
    HAVING max(months_since_signup) >= 6
)
SELECT
    r.months_since_signup,
    count(DISTINCT r.signup_month)        AS cohorts_included,
    round(avg(r.retention_pct), 1)        AS avg_retention_pct,
    round(min(r.retention_pct), 1)        AS min_retention_pct,
    round(max(r.retention_pct), 1)        AS max_retention_pct
FROM q3_cohort_retention r
WHERE r.signup_month IN (SELECT signup_month FROM complete_cohorts)
  AND r.months_since_signup <= 6
GROUP BY r.months_since_signup
ORDER BY r.months_since_signup;

-- -----------------------------------------------------------------------------
-- dash_segments — the RFM segments, ordered by the thing the stakeholder acts on.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW dash_segments AS
SELECT
    segment,
    customers,
    avg_days_since_order,
    avg_orders,
    avg_revenue,
    segment_revenue,
    pct_of_revenue,
    -- A crude priority flag so the dashboard can mark the row to act on rather
    -- than leaving the reader to work it out from four columns.
    CASE
        WHEN segment = 'at risk - was loyal' THEN 'act now'
        WHEN segment = 'champion'            THEN 'protect'
        WHEN segment = 'promising new'       THEN 'nurture'
        WHEN segment = 'lapsed'              THEN 'low priority'
        ELSE 'monitor'
    END AS recommended_action
FROM q5_rfm_summary
ORDER BY segment_revenue DESC;

-- -----------------------------------------------------------------------------
-- dash_channel_quality — acquisition channel efficiency, for the budget question.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW dash_channel_quality AS
SELECT
    channel,
    customers,
    blended_cac,
    revenue_per_customer_12mo,
    revenue_per_naira_spent,
    spend > 0 AS is_paid
FROM q8_channel_payback
ORDER BY revenue_per_naira_spent DESC NULLS LAST;
