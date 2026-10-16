-- =============================================================================
-- 01_staging.sql — cast, clean, and de-duplicate the raw_* tables.
--
-- Every decision in this file is a judgement call, and every judgement call is
-- commented with what I chose and what I gave up. That commentary is the point:
-- an interviewer can disagree with a choice, but they cannot accuse me of
-- making it by accident.
--
-- Run:  duckdb warehouse.duckdb < 01-sql-retail-warehouse/sql/01_staging.sql
-- =============================================================================

-- -----------------------------------------------------------------------------
-- stg_customers
--   * Emails are trimmed and lowercased. The source system let the same human
--     register as "USER@x.com" and " user@x.com ", which double-counts them in
--     any email-keyed join.
--   * Internal QA accounts (@test.internal) are flagged, not deleted. Deleting
--     them here would hide them from the data quality report, and someone will
--     eventually ask how many there were.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW stg_customers AS
SELECT
    CAST(customer_id AS BIGINT)                       AS customer_id,
    lower(trim(email))                                AS email,
    CAST(signup_date AS DATE)                          AS signup_date,
    date_trunc('month', CAST(signup_date AS DATE))     AS signup_month,
    -- Empty string and NULL mean the same thing here: we never captured it.
    -- 'unknown' keeps these rows in GROUP BY output instead of silently
    -- dropping ~4% of customers from every country breakdown.
    nullif(trim(country), '')                          AS country,
    coalesce(nullif(trim(country), ''), 'unknown')     AS country_filled,
    trim(acquisition_channel)                          AS acquisition_channel,
    lower(trim(email)) LIKE '%@test.internal'          AS is_test_account
FROM raw_customers;

-- -----------------------------------------------------------------------------
-- stg_products — the cleanest table in the warehouse. Cast and move on.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW stg_products AS
SELECT
    CAST(product_id AS BIGINT)    AS product_id,
    trim(product_name)            AS product_name,
    trim(category)                AS category,
    CAST(unit_cost AS DECIMAL(14, 2))  AS unit_cost,
    CAST(list_price AS DECIMAL(14, 2)) AS list_price
FROM raw_products;

-- -----------------------------------------------------------------------------
-- stg_orders
--   * order_ts arrives in two formats. ~2% of rows are DD/MM/YYYY HH:MM, the
--     rest are ISO. A plain CAST silently NULLs the minority format, which
--     deletes real revenue and biases it toward whichever weeks the broken
--     exporter was running. coalesce over two parse attempts keeps both.
--   * status has eight spellings for five states. I collapse casing, then map
--     to a revenue_recognised flag so that downstream queries never re-litigate
--     which statuses count.
--   * "Counts as revenue" = completed or shipped. Cancelled, refunded and
--     pending do not. This is the single most consequential assumption in the
--     project and it is stated once, here.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW stg_orders AS
WITH parsed AS (
    SELECT
        CAST(order_id AS BIGINT)      AS order_id,
        CAST(customer_id AS BIGINT)   AS customer_id,
        coalesce(
            try_cast(order_ts AS TIMESTAMP),
            try_strptime(order_ts, '%d/%m/%Y %H:%M')
        )                              AS order_ts,
        lower(trim(status))            AS status,
        trim(channel)                  AS order_channel,
        nullif(trim(discount_code), '') AS discount_code
    FROM raw_orders
)
SELECT
    order_id,
    customer_id,
    order_ts,
    CAST(order_ts AS DATE)                   AS order_date,
    date_trunc('month', CAST(order_ts AS DATE)) AS order_month,
    status,
    status IN ('completed', 'shipped')       AS revenue_recognised,
    order_channel,
    discount_code,
    discount_code IS NOT NULL                AS used_discount
FROM parsed;

-- -----------------------------------------------------------------------------
-- stg_order_items
--   * A retried ETL load duplicated ~1.2% of rows byte for byte, including the
--     primary key. I keep one row per order_item_id. Taking row_number over an
--     ordered window (rather than SELECT DISTINCT) makes the de-duplication
--     deterministic and survives the case where the duplicate rows differ in
--     some column I have not noticed yet.
--   * Negative quantity is how the source system encodes a return: it mutates
--     the original line instead of writing a credit note. I split the two
--     concepts apart — gross_revenue for sales, return_value for returns — so
--     that "revenue" never quietly nets off refunds without being asked to.
--   * Unit prices more than 20x list price are data entry slips (a x100 typo).
--     I flag rather than fix: I cannot know the true price, and inventing one
--     would be worse than excluding the row and saying so.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW stg_order_items AS
WITH deduped AS (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY order_item_id
            ORDER BY order_id, product_id, quantity, unit_price
        ) AS rn
    FROM raw_order_items
),
typed AS (
    SELECT
        CAST(d.order_item_id AS BIGINT)        AS order_item_id,
        CAST(d.order_id AS BIGINT)             AS order_id,
        CAST(d.product_id AS BIGINT)           AS product_id,
        CAST(d.quantity AS INTEGER)            AS quantity,
        CAST(d.unit_price AS DECIMAL(14, 2))   AS unit_price,
        p.list_price,
        p.category
    FROM deduped d
    LEFT JOIN stg_products p USING (product_id)
    WHERE d.rn = 1
)
SELECT
    order_item_id,
    order_id,
    product_id,
    category,
    quantity,
    unit_price,
    list_price,
    unit_price > list_price * 20                      AS is_price_outlier,
    quantity < 0                                      AS is_return,
    -- Both measures are gated on the same price sanity check. An earlier
    -- version gated only gross_revenue, so a refund on a mistyped line showed
    -- up as a six-figure negative customer. If you exclude a bad price from
    -- one measure you must exclude it from all of them.
    CASE WHEN quantity > 0 AND unit_price <= list_price * 20
         THEN quantity * unit_price ELSE 0 END        AS gross_revenue,
    CASE WHEN quantity < 0 AND unit_price <= list_price * 20
         THEN abs(quantity) * unit_price ELSE 0 END   AS return_value
FROM typed;

-- -----------------------------------------------------------------------------
-- stg_sessions — the behavioural table behind the funnel and device analysis.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW stg_sessions AS
SELECT
    CAST(session_id AS BIGINT)    AS session_id,
    CAST(customer_id AS BIGINT)   AS customer_id,
    CAST(session_date AS DATE)    AS session_date,
    date_trunc('month', CAST(session_date AS DATE)) AS session_month,
    trim(device)                  AS device,
    trim(source)                  AS source,
    CAST(pages_viewed AS INTEGER) AS pages_viewed,
    CAST(converted AS INTEGER) = 1 AS converted
FROM raw_sessions;

CREATE OR REPLACE VIEW stg_marketing_spend AS
SELECT
    CAST(spend_month AS DATE)           AS spend_month,
    trim(channel)                       AS channel,
    CAST(spend_ngn AS DECIMAL(16, 2))   AS spend_ngn
FROM raw_marketing_spend;

-- =============================================================================
-- Marts — the two tables every analysis query below builds on.
-- =============================================================================

-- fct_orders: one row per order, with revenue rolled up from its items and
-- orphan orders flagged. Orphans (customer_id with no customer row, from an
-- upstream GDPR deletion) stay in revenue totals but are excluded from
-- customer-level analysis: the money was real even though the customer is gone.
CREATE OR REPLACE VIEW fct_orders AS
SELECT
    o.order_id,
    o.customer_id,
    o.order_ts,
    o.order_date,
    o.order_month,
    o.status,
    o.revenue_recognised,
    o.order_channel,
    o.used_discount,
    c.customer_id IS NULL                   AS is_orphan_order,
    c.signup_month,
    c.acquisition_channel,
    c.country_filled,
    coalesce(c.is_test_account, FALSE)      AS is_test_account,
    coalesce(i.n_items, 0)                  AS n_items,
    coalesce(i.gross_revenue, 0)            AS gross_revenue,
    coalesce(i.return_value, 0)             AS return_value,
    coalesce(i.gross_revenue, 0) - coalesce(i.return_value, 0) AS net_revenue
FROM stg_orders o
LEFT JOIN stg_customers c USING (customer_id)
LEFT JOIN (
    SELECT
        order_id,
        count(*)            AS n_items,
        sum(gross_revenue)  AS gross_revenue,
        sum(return_value)   AS return_value
    FROM stg_order_items
    GROUP BY order_id
) i USING (order_id);

-- analysis_orders: the one view the analysis queries actually read.
-- Test accounts and non-recognised statuses are filtered here, once, so that no
-- individual query can forget to do it and quietly disagree with the others.
CREATE OR REPLACE VIEW analysis_orders AS
SELECT *
FROM fct_orders
WHERE revenue_recognised
  AND NOT is_test_account
  AND NOT is_orphan_order
  AND order_ts IS NOT NULL;

-- dim_customers: customer-level facts, computed once.
CREATE OR REPLACE VIEW dim_customers AS
SELECT
    c.customer_id,
    c.email,
    c.signup_date,
    c.signup_month,
    c.country_filled,
    c.acquisition_channel,
    count(o.order_id)                              AS orders_count,
    coalesce(sum(o.net_revenue), 0)                AS lifetime_revenue,
    min(o.order_date)                              AS first_order_date,
    max(o.order_date)                              AS last_order_date,
    date_diff('day', min(o.order_date), max(o.order_date)) AS active_span_days
FROM stg_customers c
LEFT JOIN analysis_orders o USING (customer_id)
WHERE NOT c.is_test_account
GROUP BY ALL;
