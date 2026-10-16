"""Benchmark three query rewrites, and print the numbers rather than claim them.

Every "I optimised a query" line on a CV is unfalsifiable. This script makes
mine falsifiable: it runs both versions, asserts they return identical results,
and reports the timing on whatever machine you run it on.

Usage:
    python 01-sql-retail-warehouse/sql/bench.py --db warehouse.duckdb
"""

from __future__ import annotations

import argparse
import re
import statistics
import time
from pathlib import Path

import duckdb

REPEATS = 9

# -- Case 1 -------------------------------------------------------------------
# Classic correlated subquery: for every order, re-scan the order table to find
# that customer's first order month.
C1_SLOW = """
SELECT o.order_month,
       sum(CASE WHEN o.order_month = (SELECT min(o2.order_month) FROM bench_orders o2
                                      WHERE o2.customer_id = o.customer_id)
                THEN o.net_revenue ELSE 0 END) AS new_rev,
       sum(CASE WHEN o.order_month <> (SELECT min(o2.order_month) FROM bench_orders o2
                                       WHERE o2.customer_id = o.customer_id)
                THEN o.net_revenue ELSE 0 END) AS ret_rev
FROM bench_orders o
GROUP BY o.order_month
ORDER BY o.order_month
"""
C1_FAST = """
WITH tagged AS (
    SELECT order_month, net_revenue,
           min(order_month) OVER (PARTITION BY customer_id) AS first_order_month
    FROM bench_orders
)
SELECT order_month,
       coalesce(sum(net_revenue) FILTER (WHERE order_month =  first_order_month), 0) AS new_rev,
       coalesce(sum(net_revenue) FILTER (WHERE order_month <> first_order_month), 0) AS ret_rev
FROM tagged
GROUP BY order_month
ORDER BY order_month
"""

# -- Case 2 -------------------------------------------------------------------
# Market basket self-join. The slow version joins the item table to itself
# directly, so an order with two skincare and three haircare lines produces six
# joined rows for one basket. It therefore *needs* count(DISTINCT order_id) to
# be correct, and that distinct-aggregate is the expensive part. The fast
# version collapses to distinct (order_id, category) pairs before the join, so
# the join is smaller and a plain count(*) is already correct.
C2_SLOW = """
SELECT a.category AS cat_a, b.category AS cat_b, count(DISTINCT a.order_id) AS orders_with_both
FROM bench_items a
JOIN bench_items b ON a.order_id = b.order_id AND a.category < b.category
GROUP BY 1, 2
HAVING count(DISTINCT a.order_id) >= 30
ORDER BY 1, 2
"""
C2_FAST = """
WITH oc AS (SELECT DISTINCT order_id, category FROM bench_items)
SELECT a.category AS cat_a, b.category AS cat_b, count(*) AS orders_with_both
FROM oc a
JOIN oc b ON a.order_id = b.order_id AND a.category < b.category
GROUP BY 1, 2
HAVING count(*) >= 30
ORDER BY 1, 2
"""

# -- Case 3 -------------------------------------------------------------------
# Predicate placement. The slow version joins all sessions to all customers and
# filters afterwards; the fast version filters each side down first. Columnar
# engines push simple predicates down on their own, so the interesting question
# is how much is left for a human to do. The answer is in the output.
C3_SLOW = """
SELECT c.acquisition_channel, count(*) AS sessions, avg(s.pages_viewed) AS avg_pages
FROM bench_sessions s
JOIN bench_customers c ON c.customer_id = s.customer_id
WHERE s.session_date >= DATE '2025-01-01'
  AND c.country_filled = 'NG'
  AND s.device = 'mobile'
GROUP BY 1
ORDER BY 2 DESC
"""
C3_FAST = """
WITH s AS (
    SELECT customer_id, pages_viewed FROM bench_sessions
    WHERE session_date >= DATE '2025-01-01' AND device = 'mobile'
),
c AS (
    SELECT customer_id, acquisition_channel FROM bench_customers
    WHERE country_filled = 'NG'
)
SELECT c.acquisition_channel, count(*) AS sessions, avg(s.pages_viewed) AS avg_pages
FROM s JOIN c ON c.customer_id = s.customer_id
GROUP BY 1
ORDER BY 2 DESC
"""

# DuckDB renders EXPLAIN as a box diagram, so pull operator names out of the
# box-drawing characters rather than trying to read whole lines.
OP_RE = re.compile(r"[\u2502\s]([A-Z][A-Z_]{3,})[\u2502\s]")

# SQL keywords and join modifiers also appear in the boxes (inside CASE
# expressions and under join nodes). They are not operators, so drop them.
NOT_OPERATORS = {
    "CASE", "WHEN", "THEN", "ELSE", "END", "NULL", "AND", "DESC", "ASC",
    "LEFT", "RIGHT", "INNER", "OUTER", "FULL", "SEMI", "ANTI", "MARK",
    "TRUE", "FALSE", "DISTINCT", "FILTER",
}

CASES = [
    ("1. correlated subquery -> window function", C1_SLOW, C1_FAST),
    ("2. self-join on duplicated rows -> distinct pairs first", C2_SLOW, C2_FAST),
    ("3. filter after join -> filter before join", C3_SLOW, C3_FAST),
]


def normalise(rows):
    out = []
    for r in rows:
        out.append(tuple(round(float(v), 2) if isinstance(v, (int, float)) and not isinstance(v, bool)
                         else (round(float(v), 2) if hasattr(v, "quantize") else v)
                         for v in r))
    return out


def bench(con, sql: str) -> tuple[float, float]:
    con.execute(sql).fetchall()  # warm the cache so we measure the plan, not the I/O
    samples = []
    for _ in range(REPEATS):
        t0 = time.perf_counter()
        con.execute(sql).fetchall()
        samples.append((time.perf_counter() - t0) * 1000)
    return min(samples), statistics.median(samples)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="warehouse.duckdb", type=Path)
    ap.add_argument(
        "--scale", default=1, type=int,
        help="Replicate the fact tables N times. A rewrite that wins by a "
             "constant factor at 1x and by a growing factor at 10x is an "
             "algorithmic win; one that stays flat was never the bottleneck.",
    )
    args = ap.parse_args()

    con = duckdb.connect(str(args.db))
    staging = Path(__file__).with_name("01_staging.sql")
    con.execute(staging.read_text())

    # Materialise to tables so we time the query plan, not repeated view
    # expansion over CSV-backed scans.
    scale_clause = ""
    if args.scale > 1:
        # Replicate with a distinct customer_id offset per copy, so the
        # per-customer cardinality stays realistic instead of making every
        # partition N times bigger.
        scale_clause = f", range(0, {args.scale}) AS r(copy)"

    if args.scale > 1:
        con.execute(f'''CREATE OR REPLACE TABLE bench_orders AS
            SELECT * REPLACE (customer_id + r.copy * 1000000 AS customer_id,
                              order_id + r.copy * 10000000 AS order_id)
            FROM analysis_orders{scale_clause}''')
    else:
        con.execute("CREATE OR REPLACE TABLE bench_orders AS SELECT * FROM analysis_orders")
    con.execute("""CREATE OR REPLACE TABLE bench_items AS
                   SELECT i.* FROM stg_order_items i
                   JOIN analysis_orders o USING (order_id)
                   WHERE i.category IS NOT NULL AND NOT i.is_return""")
    if args.scale > 1:
        con.execute(f'''CREATE OR REPLACE TABLE bench_sessions AS
            SELECT * REPLACE (customer_id + r.copy * 1000000 AS customer_id)
            FROM stg_sessions{scale_clause}''')
        con.execute(f'''CREATE OR REPLACE TABLE bench_items_x AS
            SELECT * REPLACE (order_id + r.copy * 10000000 AS order_id,
                              order_item_id + r.copy * 10000000 AS order_item_id)
            FROM bench_items{scale_clause}''')
        con.execute("CREATE OR REPLACE TABLE bench_items AS SELECT * FROM bench_items_x")
        con.execute("DROP TABLE bench_items_x")
    else:
        con.execute("CREATE OR REPLACE TABLE bench_sessions AS SELECT * FROM stg_sessions")
    if args.scale > 1:
        con.execute(f'''CREATE OR REPLACE TABLE bench_customers AS
            SELECT * REPLACE (customer_id + r.copy * 1000000 AS customer_id)
            FROM stg_customers{scale_clause}''')
    else:
        con.execute("CREATE OR REPLACE TABLE bench_customers AS SELECT * FROM stg_customers")

    rows = con.execute("SELECT count(*) FROM bench_orders").fetchone()[0]
    items = con.execute("SELECT count(*) FROM bench_items").fetchone()[0]
    sess = con.execute("SELECT count(*) FROM bench_sessions").fetchone()[0]
    print(f"DuckDB {duckdb.__version__}  |  scale {args.scale}x  |  "
          f"orders {rows:,}  items {items:,}  sessions {sess:,}\n")

    print(f"{'case':<56}{'slow (ms)':>11}{'fast (ms)':>11}{'speedup':>9}  same?")
    print("-" * 95)
    for name, slow, fast in CASES:
        same = normalise(con.execute(slow).fetchall()) == normalise(con.execute(fast).fetchall())
        _, s_med = bench(con, slow)
        _, f_med = bench(con, fast)
        print(f"{name:<56}{s_med:>11.1f}{f_med:>11.1f}{s_med / f_med:>8.1f}x  {'yes' if same else 'NO'}")

    print("\nPlans (the reason, not just the number):")
    for name, slow, fast in CASES:
        print(f"\n### {name}")
        for label, sql in (("slow", slow), ("fast", fast)):
            plan = con.execute("EXPLAIN " + sql).fetchall()[0][1]
            ops = [o for o in OP_RE.findall(plan) if o not in NOT_OPERATORS]
            print(f"  {label}: {' -> '.join(dict.fromkeys(ops))}")


if __name__ == "__main__":
    main()
