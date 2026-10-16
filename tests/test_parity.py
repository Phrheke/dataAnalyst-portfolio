"""The dbt project and the hand-written SQL must agree, to the naira.

Two independent implementations of the same logic agreeing is the cheapest real
check on either one. When they disagree, one of them is wrong and I would
otherwise have no way of knowing which numbers in the README to trust.

Skipped if the dbt warehouse has not been built. Build it with:
    cd 01-sql-retail-warehouse/dbt && dbt build --profiles-dir .
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
DBT_DB = ROOT / "dbt_warehouse.duckdb"

# (description, hand-written SQL, dbt equivalent)
PAIRS = [
    ("orders in the analysis set",
     "SELECT count(*) FROM analysis_orders",
     "SELECT count(*) FROM main_marts.analysis_orders"),
    ("net revenue",
     "SELECT round(sum(net_revenue)) FROM analysis_orders",
     "SELECT round(sum(net_revenue)) FROM main_marts.analysis_orders"),
    ("customers in the dimension",
     "SELECT count(*) FROM dim_customers",
     "SELECT count(*) FROM main_marts.dim_customers"),
    ("total lifetime revenue",
     "SELECT round(sum(lifetime_revenue)) FROM dim_customers",
     "SELECT round(sum(lifetime_revenue)) FROM main_marts.dim_customers"),
    ("staged item rows after de-duplication",
     "SELECT count(*) FROM stg_order_items",
     "SELECT count(*) FROM main_staging.stg_order_items"),
    ("staged orders",
     "SELECT count(*) FROM stg_orders",
     "SELECT count(*) FROM main_staging.stg_orders"),
    ("price outliers flagged",
     "SELECT count(*) FROM stg_order_items WHERE is_price_outlier",
     "SELECT count(*) FROM main_staging.stg_order_items WHERE is_price_outlier"),
    ("month-1 retention, averaged",
     "SELECT round(avg(retention_pct), 2) FROM q3_cohort_retention WHERE months_since_signup = 1",
     "SELECT round(avg(retention_pct), 2) FROM main_marts.mart_cohort_retention "
     "WHERE months_since_signup = 1"),
]


@pytest.fixture(scope="module")
def dbt_con():
    if not DBT_DB.exists():
        pytest.skip(f"{DBT_DB.name} not built; run dbt build first")
    return duckdb.connect(str(DBT_DB), read_only=True)


@pytest.fixture(scope="module")
def sql_con():
    """A warehouse built from the repository's own data/raw, to match dbt's input."""
    raw = ROOT / "data" / "raw"
    if not (raw / "orders.csv").exists():
        pytest.skip("data/raw not generated; run make data first")
    c = duckdb.connect(":memory:")
    for t in ["customers", "products", "orders", "order_items", "sessions", "marketing_spend"]:
        src = (raw / f"{t}.csv").resolve().as_posix()
        c.execute(
            f"CREATE TABLE raw_{t} AS "
            f"SELECT * FROM read_csv('{src}', header = true, all_varchar = true)"
        )
    sql = ROOT / "01-sql-retail-warehouse" / "sql"
    c.execute((sql / "01_staging.sql").read_text())
    c.execute((sql / "02_analysis.sql").read_text())
    return c


@pytest.mark.parametrize("label,hand_sql,dbt_sql", PAIRS, ids=[p[0] for p in PAIRS])
def test_implementations_agree(sql_con, dbt_con, label, hand_sql, dbt_sql):
    hand = sql_con.execute(hand_sql).fetchone()[0]
    dbt = dbt_con.execute(dbt_sql).fetchone()[0]
    assert hand == dbt, f"{label}: hand-written SQL gave {hand}, dbt gave {dbt}"
