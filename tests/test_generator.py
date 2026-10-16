"""The generator must be deterministic and must actually plant the faults.

If the faults stop appearing, the data quality project becomes a fiction, and
these tests are what stop that happening silently during a refactor.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _gen(out: Path, seed: int = 42) -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "src" / "generate_warehouse.py"),
         "--out", str(out), "--sample-out", str(out / "s"), "--seed", str(seed)],
        check=True, capture_output=True,
    )


def test_same_seed_is_byte_identical(tmp_path):
    """Reproducibility is the claim the README makes. This is the proof."""
    a, b = tmp_path / "a", tmp_path / "b"
    _gen(a)
    _gen(b)
    for name in ["customers", "orders", "order_items", "sessions", "products"]:
        assert (a / f"{name}.csv").read_bytes() == (b / f"{name}.csv").read_bytes(), name


def test_different_seed_changes_output(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _gen(a, seed=42)
    _gen(b, seed=43)
    assert (a / "orders.csv").read_bytes() != (b / "orders.csv").read_bytes()


def test_planted_faults_are_present(con):
    """Each of the eight documented faults must exist in the raw tables."""
    def q(sql):
        return con.execute(sql).fetchone()[0]

    # 1. Email case / whitespace inconsistency.
    assert q("SELECT count(*) FROM raw_customers WHERE email <> lower(trim(email))") > 100

    # 2. Internal test accounts.
    assert q("SELECT count(*) FROM raw_customers WHERE email LIKE '%@test.internal'") > 0

    # 3. Missing country. DuckDB reads an unquoted empty CSV field as NULL, so
    #    accept either representation -- the staging layer normalises both.
    assert q(
        "SELECT count(*) FROM raw_customers "
        "WHERE country IS NULL OR trim(country) = ''"
    ) > 100

    # 4. Two timestamp formats.
    assert q("SELECT count(*) FROM raw_orders WHERE try_cast(order_ts AS TIMESTAMP) IS NULL") > 0

    # 5. Price outliers.
    assert q("SELECT count(*) FROM stg_order_items WHERE is_price_outlier") > 0

    # 6. Returns as negative quantity.
    assert q("SELECT count(*) FROM stg_order_items WHERE is_return") > 0

    # 7. Duplicate item rows.
    dupes = q("SELECT count(*) - count(DISTINCT order_item_id) FROM raw_order_items")
    assert dupes > 0

    # 8. Orphan orders.
    assert q("SELECT count(*) FROM fct_orders WHERE is_orphan_order") > 0


def test_signal_is_present_not_just_noise(con):
    """The affinity and seasonality the analysis claims to find must be real.

    A uniformly random generator produces lift ~1.0 everywhere, and then the
    market-basket query 'works' while discovering nothing.
    """
    lift = con.execute(
        "SELECT lift FROM q10_category_affinity "
        "WHERE cat_a = 'haircare' AND cat_b = 'skincare'"
    ).fetchone()[0]
    assert lift > 1.2, f"haircare/skincare lift should be well above 1.0, got {lift}"

    # November must beat the trailing average in both years.
    nov = con.execute("""
        SELECT order_month, net_revenue, revenue_3mo_avg
        FROM q1_revenue_trend WHERE month(order_month) = 11
    """).fetchall()
    assert len(nov) == 2
    for month, revenue, trailing in nov:
        assert revenue > trailing, f"{month} should spike above its trailing average"
