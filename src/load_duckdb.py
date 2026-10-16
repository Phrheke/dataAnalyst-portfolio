"""Load the raw CSVs into DuckDB as all-VARCHAR `raw_*` tables.

Everything lands as text on purpose. Real ingestion gives you strings and
leaves the casting to you, and casting is where you discover that 2% of your
timestamps are in a different format. If the loader silently coerced types,
the data quality work in this project would have nothing to find.

Usage:
    python src/load_duckdb.py --db warehouse.duckdb --raw data/raw
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

TABLES = ["customers", "products", "orders", "order_items", "sessions", "marketing_spend"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="warehouse.duckdb", type=Path)
    ap.add_argument("--raw", default="data/raw", type=Path)
    args = ap.parse_args()

    missing = [t for t in TABLES if not (args.raw / f"{t}.csv").exists()]
    if missing:
        raise SystemExit(
            f"Missing CSVs for {', '.join(missing)} in {args.raw}. "
            "Run: python src/generate_warehouse.py"
        )

    con = duckdb.connect(str(args.db))
    for t in TABLES:
        src = (args.raw / f"{t}.csv").resolve().as_posix()
        con.execute(f"DROP TABLE IF EXISTS raw_{t}")
        con.execute(
            f"""
            CREATE TABLE raw_{t} AS
            SELECT * FROM read_csv('{src}', header = true, all_varchar = true)
            """
        )
        n = con.execute(f"SELECT count(*) FROM raw_{t}").fetchone()[0]
        print(f"  raw_{t:18} {n:>9,} rows")

    con.close()
    print(f"Loaded into {args.db}")


if __name__ == "__main__":
    main()
