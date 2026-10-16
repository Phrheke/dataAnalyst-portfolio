"""Export the dashboard mart to a single JSON file for the web dashboard.

Why a JSON export rather than a live database connection: the dashboard is
published on GitHub Pages, which serves static files only. Exporting is also
what a BI tool does when you schedule an extract, so the shape of this file is
the shape a Tableau or Power BI extract would have.

Rounding happens here, once, not in the chart code. A number formatted in three
different places ends up with three different values.

Usage:
    python 03-dashboard-retention/src/export_dashboard_data.py --db warehouse.duckdb
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
SQL_FILES = [
    ROOT / "01-sql-retail-warehouse" / "sql" / "01_staging.sql",
    ROOT / "01-sql-retail-warehouse" / "sql" / "02_analysis.sql",
    ROOT / "03-dashboard-retention" / "sql" / "dashboard_mart.sql",
]
OUT = ROOT / "docs" / "dashboard" / "data.json"

VIEWS = [
    "dash_kpi",
    "dash_revenue_split",
    "dash_cohort_heatmap",
    "dash_retention_curve",
    "dash_segments",
    "dash_channel_quality",
]


def jsonable(value):
    """Decimal and date are not JSON types. Convert once, here."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def fetch(con, view: str) -> list[dict]:
    cur = con.execute(f"SELECT * FROM {view}")
    cols = [d[0] for d in cur.description]
    return [
        dict(zip(cols, (jsonable(v) for v in row), strict=True))
        for row in cur.fetchall()
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="warehouse.duckdb", type=Path)
    ap.add_argument("--out", default=OUT, type=Path)
    args = ap.parse_args()

    if not args.db.exists():
        raise SystemExit(f"{args.db} not found. Run: make data warehouse")

    con = duckdb.connect(str(args.db))
    for path in SQL_FILES:
        con.execute(path.read_text())

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "synthetic warehouse, see src/generate_warehouse.py",
    }
    for view in VIEWS:
        rows = fetch(con, view)
        payload[view] = rows
        print(f"  {view:<24} {len(rows):>4} rows")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=1)
    args.out.write_text(body)

    # Also emit a JS module-free global. `fetch("data.json")` is blocked by the
    # browser's same-origin policy on file:// URLs, so a reviewer who opens
    # index.html by double-clicking it would see an empty dashboard. A <script>
    # tag has no such restriction, so the page works both locally and on
    # GitHub Pages with no local web server required.
    js = args.out.with_suffix(".js")
    js.write_text(f"window.DASHBOARD_DATA = {body};\n")

    print(f"\nWrote {args.out} ({args.out.stat().st_size / 1024:.0f} KB)")
    print(f"Wrote {js} ({js.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
