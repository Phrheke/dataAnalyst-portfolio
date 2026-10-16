"""Produce an offline stand-in for the collected pageviews data.

WHY THIS EXISTS, STATED PLAINLY: `collect.py` needs outbound internet access.
This file generates a dataset with the same schema and the same qualitative
structure so that the analysis, the tests and the charts all run on a clean
clone with no network. It is a **fixture, not data**. No finding in this project
is a claim about real Wikipedia traffic unless `data/provenance.json` is
present, which only `collect.py` writes.

To use real data instead, run (takes about 20 seconds):

    python 02-python-pageviews/src/collect.py --start 2023-01-01 --end 2025-12-31

and re-run the analysis. The analysis script reports which source it used.

The structure planted here -- a weekday/weekend gap that is large for
professional topics, small for tooling and reversed for leisure -- is what the
hypothesis test is built to measure. Planting it means the test has something to
find; the test is still a real test, and it would correctly fail to reject if
the effect were absent.

Usage:
    python 02-python-pageviews/src/simulate_offline.py --out 02-python-pageviews/data
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path

import numpy as np

# article -> (topic class, baseline daily views, weekend multiplier)
ARTICLES = {
    "Data_analysis":                 ("professional", 1850, 0.63),
    "Statistics":                    ("professional", 2400, 0.66),
    "Machine_learning":              ("professional", 5200, 0.69),
    "SQL":                           ("tooling",      3100, 0.74),
    "Python_(programming_language)": ("tooling",      9800, 0.78),
    "Microsoft_Excel":               ("tooling",      4300, 0.71),
    "Association_football":          ("leisure",      6100, 1.18),
    "Netflix":                       ("leisure",      7400, 1.09),
}

# Days when the working-week pattern breaks down. A real analysis has to decide
# what to do about these, which is the point of including them.
HOLIDAYS = {
    (1, 1), (12, 24), (12, 25), (12, 26), (12, 31),
    (7, 4), (11, 28), (11, 27),
}


def build(start: date, end: date, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    n_days = (end - start).days + 1

    for article, (topic_class, base, weekend_mult) in ARTICLES.items():
        # A slow secular trend, different per article, so the series is not
        # stationary and the analysis has to cope with that.
        trend = rng.uniform(-0.25, 0.55)
        # Academic-year seasonality: term-time interest in technical topics.
        season_amp = 0.12 if topic_class != "leisure" else 0.05
        season_phase = rng.uniform(0, 2 * np.pi)

        # AR(1) residuals. Real pageview series are strongly autocorrelated --
        # a day with heavy traffic is followed by another one, because the
        # drivers (a link from a popular page, a news cycle, a course
        # assignment) persist for days. Independent noise would make this
        # fixture far easier to analyse than real data, and would specifically
        # destroy the pseudo-replication effect the analysis is built to
        # demonstrate.
        phi = rng.uniform(0.55, 0.75)
        resid = 0.0

        for i in range(n_days):
            day = start + timedelta(days=i)
            t = i / n_days

            level = base * (1 + trend * t)
            level *= 1 + season_amp * np.sin(2 * np.pi * t * (n_days / 365.25) + season_phase)

            if day.weekday() >= 5:
                level *= weekend_mult
            if (day.month, day.day) in HOLIDAYS:
                level *= 0.72 if topic_class != "leisure" else 1.25

            # Overdispersed, autocorrelated noise. Pageview counts are much
            # noisier than Poisson, and successive days are correlated.
            resid = phi * resid + np.sqrt(1 - phi**2) * rng.normal(0, 1)
            views = int(max(0, level * (1 + 0.22 * resid)))

            # Occasional traffic spike from an external link or news event.
            # Kept deliberately modest: an earlier version used 0.4% of days at
            # 3-14x, whose variance was ten times that of the AR noise and
            # crushed the measured autocorrelation from 0.65 down to 0.09. A
            # fixture whose planted structure is drowned out by its own
            # outliers is not a useful fixture.
            if rng.random() < 0.0015:
                views = int(views * rng.uniform(2.5, 6.0))

            rows.append({
                "article": article,
                "topic_class": topic_class,
                "date": day.isoformat(),
                "views": views,
            })

    # Missing days: the API genuinely has gaps, and dropping them silently
    # versus interpolating them is a decision the analysis has to make.
    keep = rng.random(len(rows)) > 0.006
    rows = [r for r, k in zip(rows, keep, strict=True) if k]
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2023-01-01", type=lambda s: date.fromisoformat(s))
    ap.add_argument("--end", default="2025-12-31", type=lambda s: date.fromisoformat(s))
    ap.add_argument("--out", default="02-python-pageviews/data", type=Path)
    ap.add_argument("--seed", default=7, type=int)
    args = ap.parse_args()

    rows = build(args.start, args.end, args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "pageviews.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["article", "topic_class", "date", "views"])
        w.writeheader()
        w.writerows(rows)

    # Deliberately NOT writing provenance.json. Its absence is how the analysis
    # knows this is a fixture and labels its own output accordingly.
    marker = args.out / "SIMULATED.txt"
    marker.write_text(
        "This directory holds SIMULATED pageview data generated by "
        "src/simulate_offline.py.\n"
        "It is a fixture so the analysis runs without network access.\n"
        "Run src/collect.py to replace it with real Wikimedia API data.\n"
    )
    print(f"Wrote {path} ({len(rows):,} rows) + SIMULATED.txt marker")
    print("This is a FIXTURE. Run collect.py for real data.")


if __name__ == "__main__":
    main()
