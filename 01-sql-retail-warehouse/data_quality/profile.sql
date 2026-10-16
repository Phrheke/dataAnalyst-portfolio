-- =============================================================================
-- profile.sql — run this BEFORE writing a single analysis query.
--
-- Most portfolio SQL projects open with a revenue chart. This one opens with an
-- audit, because the first question a working analyst gets asked about a new
-- number is "do you trust the data?" and the only good answer is a count.
--
-- Run:  duckdb warehouse.duckdb < 01-sql-retail-warehouse/data_quality/profile.sql
-- Requires 01_staging.sql to have been run first.
-- =============================================================================

.print '\n=== 1. Row counts: raw vs staged ==========================================='
-- Any gap between these two columns is a row I dropped. If I cannot explain a
-- gap, I have a bug, not a cleaning decision.
SELECT 'customers'   AS table_name, (SELECT count(*) FROM raw_customers)   AS raw_rows, (SELECT count(*) FROM stg_customers)   AS staged_rows
UNION ALL SELECT 'products',        (SELECT count(*) FROM raw_products),        (SELECT count(*) FROM stg_products)
UNION ALL SELECT 'orders',          (SELECT count(*) FROM raw_orders),          (SELECT count(*) FROM stg_orders)
UNION ALL SELECT 'order_items',     (SELECT count(*) FROM raw_order_items),     (SELECT count(*) FROM stg_order_items)
UNION ALL SELECT 'sessions',        (SELECT count(*) FROM raw_sessions),        (SELECT count(*) FROM stg_sessions)
ORDER BY table_name;

.print '\n=== 2. Null and blank rates by column ======================================'
-- Expressed as a percentage, because "412 nulls" means nothing without a
-- denominator and every stakeholder asks for the percentage anyway.
SELECT 'customers.country' AS column_name,
       count(*) AS total_rows,
       count(*) FILTER (WHERE country IS NULL) AS missing,
       round(100.0 * count(*) FILTER (WHERE country IS NULL) / count(*), 2) AS pct_missing
FROM stg_customers
UNION ALL
SELECT 'orders.order_ts', count(*), count(*) FILTER (WHERE order_ts IS NULL),
       round(100.0 * count(*) FILTER (WHERE order_ts IS NULL) / count(*), 2)
FROM stg_orders
UNION ALL
SELECT 'orders.discount_code', count(*), count(*) FILTER (WHERE discount_code IS NULL),
       round(100.0 * count(*) FILTER (WHERE discount_code IS NULL) / count(*), 2)
FROM stg_orders
UNION ALL
SELECT 'order_items.category (join miss)', count(*), count(*) FILTER (WHERE category IS NULL),
       round(100.0 * count(*) FILTER (WHERE category IS NULL) / count(*), 2)
FROM stg_order_items
ORDER BY pct_missing DESC;

.print '\n=== 3. Primary key uniqueness =============================================='
-- The ETL retry that duplicated order_item rows is invisible until you count
-- keys against rows. This check is the reason stg_order_items de-duplicates.
SELECT 'raw_order_items.order_item_id' AS key_name,
       count(*) AS rows,
       count(DISTINCT order_item_id) AS distinct_keys,
       count(*) - count(DISTINCT order_item_id) AS duplicate_rows
FROM raw_order_items
UNION ALL
SELECT 'raw_orders.order_id', count(*), count(DISTINCT order_id), count(*) - count(DISTINCT order_id)
FROM raw_orders
UNION ALL
SELECT 'raw_customers.customer_id', count(*), count(DISTINCT customer_id), count(*) - count(DISTINCT customer_id)
FROM raw_customers
UNION ALL
-- Email is not the declared key, but it is the one humans assume is unique.
-- Checking it after normalisation catches the casing duplicates.
SELECT 'stg_customers.email (normalised)', count(*), count(DISTINCT email), count(*) - count(DISTINCT email)
FROM stg_customers;

.print '\n=== 4. Referential integrity ==============================================='
-- Orphan orders are the GDPR deletions. They carry real revenue, so the right
-- answer is to quantify them, not to pretend the join was clean.
SELECT
    count(*)                                                   AS orphan_orders,
    round(100.0 * count(*) / (SELECT count(*) FROM stg_orders), 2) AS pct_of_orders,
    sum(gross_revenue)                                         AS revenue_at_stake
FROM fct_orders
WHERE is_orphan_order;

SELECT count(*) AS items_with_unknown_product
FROM stg_order_items
WHERE category IS NULL;

.print '\n=== 5. Categorical vocabulary (the casing problem) ========================='
-- Eight spellings, five real states. Grouping on the raw column would split
-- "completed" revenue across three rows.
SELECT status AS raw_status, count(*) AS orders
FROM raw_orders GROUP BY status ORDER BY orders DESC;

SELECT status AS cleaned_status, revenue_recognised, count(*) AS orders
FROM stg_orders GROUP BY status, revenue_recognised ORDER BY orders DESC;

.print '\n=== 6. Numeric distributions and outliers =================================='
-- Percentiles rather than min/max/avg: the mean of a column with a x100 typo
-- in it is a number that describes nothing.
SELECT
    count(*)                                        AS item_rows,
    min(unit_price)                                 AS p0,
    quantile_cont(unit_price, 0.25)                 AS p25,
    quantile_cont(unit_price, 0.50)                 AS p50,
    quantile_cont(unit_price, 0.95)                 AS p95,
    quantile_cont(unit_price, 0.999)                AS p999,
    max(unit_price)                                 AS p100,
    count(*) FILTER (WHERE is_price_outlier)        AS flagged_outliers,
    count(*) FILTER (WHERE is_return)               AS negative_quantity_rows
FROM stg_order_items;

-- The flagged rows themselves, so a reviewer can judge the rule rather than
-- trust it. A threshold with no evidence behind it is a guess.
SELECT order_item_id, product_id, category, quantity, unit_price, list_price,
       round(unit_price / list_price, 1) AS price_vs_list_ratio
FROM stg_order_items
WHERE is_price_outlier
ORDER BY price_vs_list_ratio DESC
LIMIT 10;

.print '\n=== 7. Timeliness: does every month have data? ============================='
-- A month with a suspicious dip is usually a broken pipeline, not a bad month
-- for the business. Checking it here stops me from writing that up as a finding.
SELECT order_month,
       count(*)                       AS orders,
       count(DISTINCT customer_id)    AS customers,
       sum(net_revenue)               AS net_revenue
FROM analysis_orders
GROUP BY order_month
ORDER BY order_month;

.print '\n=== 8. Test-account contamination =========================================='
SELECT
    count(*) FILTER (WHERE is_test_account)  AS test_accounts,
    count(*)                                 AS all_customers,
    round(100.0 * count(*) FILTER (WHERE is_test_account) / count(*), 2) AS pct
FROM stg_customers;
