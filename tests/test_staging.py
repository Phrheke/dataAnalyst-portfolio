"""Invariants the staging layer must hold.

These are the assertions I would otherwise make verbally in an interview
("I de-duplicated the items table") and cannot prove. Here they are executable.
"""

from __future__ import annotations

import pytest


def scalar(con, sql):
    return con.execute(sql).fetchone()[0]


def test_deduplication_removes_exactly_the_duplicates(con):
    raw = scalar(con, "SELECT count(*) FROM raw_order_items")
    distinct_keys = scalar(con, "SELECT count(DISTINCT order_item_id) FROM raw_order_items")
    staged = scalar(con, "SELECT count(*) FROM stg_order_items")
    assert staged == distinct_keys
    assert staged < raw


def test_order_item_id_is_unique_after_staging(con):
    assert scalar(con, """
        SELECT count(*) - count(DISTINCT order_item_id) FROM stg_order_items
    """) == 0


def test_every_timestamp_parses(con):
    """The two-format parse must recover 100% of rows.

    If upstream ever adds a third format this test fails, which is the point:
    the alternative is silently losing revenue from whichever weeks the new
    exporter was running.
    """
    assert scalar(con, "SELECT count(*) FROM stg_orders WHERE order_ts IS NULL") == 0
    # And the awkward format really was present, so the test is not vacuous.
    assert scalar(con, """
        SELECT count(*) FROM raw_orders WHERE try_cast(order_ts AS TIMESTAMP) IS NULL
    """) > 0


def test_status_vocabulary_is_collapsed(con):
    raw_spellings = scalar(con, "SELECT count(DISTINCT status) FROM raw_orders")
    clean_states = scalar(con, "SELECT count(DISTINCT status) FROM stg_orders")
    assert raw_spellings > clean_states
    assert clean_states == 5


def test_revenue_measures_are_never_negative(con):
    """gross_revenue and return_value are magnitudes; net_revenue may be negative."""
    assert scalar(con, "SELECT count(*) FROM stg_order_items WHERE gross_revenue < 0") == 0
    assert scalar(con, "SELECT count(*) FROM stg_order_items WHERE return_value < 0") == 0


def test_price_outliers_are_excluded_from_both_measures(con):
    """The regression test for a bug I shipped and then fixed.

    The first version gated gross_revenue on the price sanity check but not
    return_value, so a refund on a x100 mistyped line produced a customer with
    negative six-figure lifetime revenue. Both measures must be gated.
    """
    leaked = scalar(con, """
        SELECT count(*) FROM stg_order_items
        WHERE is_price_outlier AND (gross_revenue > 0 OR return_value > 0)
    """)
    assert leaked == 0

    # No customer should have a catastrophically negative lifetime value. Small
    # negatives are legitimate (a refund larger than that window's purchases).
    worst = scalar(con, "SELECT coalesce(min(lifetime_revenue), 0) FROM dim_customers")
    assert worst > -200_000, f"suspiciously negative lifetime revenue: {worst}"


def test_order_revenue_equals_sum_of_its_items(con):
    """Guard against a join fan-out in fct_orders.

    A uniqueness test on order_id would not catch this: the join can produce
    one row per order while the revenue column is multiplied.
    """
    mismatches = scalar(con, """
        WITH item_level AS (
            SELECT order_id, sum(gross_revenue) AS gross_revenue
            FROM stg_order_items GROUP BY order_id
        )
        SELECT count(*)
        FROM fct_orders o
        LEFT JOIN item_level i USING (order_id)
        WHERE abs(o.gross_revenue - coalesce(i.gross_revenue, 0)) > 0.01
    """)
    assert mismatches == 0


def test_analysis_orders_applies_every_exclusion(con):
    assert scalar(con, """
        SELECT count(*) FROM analysis_orders
        WHERE NOT revenue_recognised OR is_test_account OR is_orphan_order
    """) == 0
    # And the exclusions actually removed something.
    assert (scalar(con, "SELECT count(*) FROM analysis_orders")
            < scalar(con, "SELECT count(*) FROM fct_orders"))


def test_orphan_orders_are_flagged_not_dropped(con):
    """The revenue is real even though the customer record is gone."""
    orphans = scalar(con, "SELECT count(*) FROM fct_orders WHERE is_orphan_order")
    assert orphans > 0
    assert scalar(con, """
        SELECT count(*) FROM fct_orders
        WHERE is_orphan_order AND customer_id IS NULL
    """) == 0  # the order keeps its (dangling) customer_id


def test_retention_is_a_percentage(con):
    bad = scalar(con, """
        SELECT count(*) FROM q3_cohort_retention
        WHERE retention_pct < 0 OR retention_pct > 100
    """)
    assert bad == 0


def test_cohort_sizes_are_measured_at_signup(con):
    """Cohort size must equal the number of signups, not the number of buyers.

    Using month-0 buyers as the denominator inflates every later month. This
    test pins the definition the README claims.
    """
    rows = con.execute("""
        SELECT r.signup_month, max(r.cohort_size) AS claimed,
               (SELECT count(*) FROM stg_customers c
                WHERE c.signup_month = r.signup_month AND NOT c.is_test_account) AS actual
        FROM q3_cohort_retention r
        GROUP BY r.signup_month
    """).fetchall()
    assert rows
    for month, claimed, actual in rows:
        assert claimed == actual, f"{month}: cohort size {claimed} != {actual} signups"


@pytest.mark.parametrize("view", [
    "q1_revenue_trend", "q2_new_vs_returning", "q3_cohort_retention",
    "q3_cohort_retention_pivot", "q4_ltv_curve", "q5_rfm_segments",
    "q5_rfm_summary", "q6_revenue_concentration", "q7_repeat_interval",
    "q8_channel_payback", "q9_conversion_by_segment", "q10_category_affinity",
])
def test_every_analysis_view_returns_rows(con, view):
    """A query that runs but returns nothing is a broken query."""
    assert scalar(con, f"SELECT count(*) FROM {view}") > 0


def test_revenue_concentration_sums_to_100(con):
    total = scalar(con, "SELECT round(sum(pct_of_revenue)) FROM q6_revenue_concentration")
    assert total == 100
    final = scalar(con, """
        SELECT cumulative_pct FROM q6_revenue_concentration
        ORDER BY revenue_decile DESC LIMIT 1
    """)
    assert final == 100.0


def test_ntile_segments_are_deterministic(con):
    """RFM segment sizes must not change between runs.

    NTILE assigns buckets by row position, so an ORDER BY that is not a total
    order lets the engine place tied rows in any sequence -- and DuckDB's
    parallel scan does vary run to run. Before `customer_id` was added as a
    tiebreaker, three consecutive runs of Q5 put 1,006 / 1,003 / 1,029
    customers in the 'at risk' segment, and the dashboard disagreed with the
    README as a result.

    Re-creating the views and re-querying is the cheap way to catch a
    regression if anyone edits those ORDER BY clauses.
    """
    from pathlib import Path

    sql = (Path(__file__).resolve().parents[1]
           / "01-sql-retail-warehouse" / "sql" / "02_analysis.sql").read_text()

    def snapshot():
        con.execute(sql)
        return con.execute("""
            SELECT segment, customers, pct_of_revenue
            FROM q5_rfm_summary ORDER BY segment
        """).fetchall()

    first = snapshot()
    for _ in range(3):
        assert snapshot() == first, "RFM segment sizes changed between runs"


def test_revenue_deciles_are_deterministic(con):
    """Same tiebreaker rule, applied to Q6's decile assignment."""
    from pathlib import Path

    sql = (Path(__file__).resolve().parents[1]
           / "01-sql-retail-warehouse" / "sql" / "02_analysis.sql").read_text()

    def snapshot():
        con.execute(sql)
        return con.execute("""
            SELECT revenue_decile, customers, pct_of_revenue
            FROM q6_revenue_concentration ORDER BY revenue_decile
        """).fetchall()

    first = snapshot()
    for _ in range(3):
        assert snapshot() == first
