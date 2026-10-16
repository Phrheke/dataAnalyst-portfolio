"""Shared fixtures. Builds the warehouse once per test session."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "01-sql-retail-warehouse" / "sql"


@pytest.fixture(scope="session")
def raw_dir(tmp_path_factory) -> Path:
    """Generate the raw CSVs into a temp directory, not the repo's data/."""
    out = tmp_path_factory.mktemp("raw")
    subprocess.run(
        [sys.executable, str(ROOT / "src" / "generate_warehouse.py"),
         "--out", str(out), "--sample-out", str(out / "sample"), "--seed", "42"],
        check=True, capture_output=True,
    )
    return out


@pytest.fixture(scope="session")
def con(raw_dir, tmp_path_factory):
    """A DuckDB connection with raw tables loaded and the staging layer built."""
    db = tmp_path_factory.mktemp("db") / "test.duckdb"
    subprocess.run(
        [sys.executable, str(ROOT / "src" / "load_duckdb.py"),
         "--db", str(db), "--raw", str(raw_dir)],
        check=True, capture_output=True,
    )
    c = duckdb.connect(str(db))
    c.execute((SQL / "01_staging.sql").read_text())
    c.execute((SQL / "02_analysis.sql").read_text())
    return c


def scalar(con, sql):
    return con.execute(sql).fetchone()[0]
