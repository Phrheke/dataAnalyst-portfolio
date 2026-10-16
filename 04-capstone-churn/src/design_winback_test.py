"""Design the winback experiment the churn model implies, before running it.

A churn model that produces a risk score and stops is not a result, it is a
spreadsheet. This script closes the loop: it takes the model's targetable
segment, works out whether that segment is even large enough to measure the
effect anyone would care about, and prices the outcome.

Doing the power analysis *first* is the point. The common failure is to run the
campaign, get p = 0.21, and conclude the campaign does not work — when the test
never had the sample size to detect a plausible effect in the first place.

Usage:
    python 04-capstone-churn/src/design_winback_test.py --db warehouse.duckdb
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
from experiment import (
    analyse_two_proportions,
    minimum_detectable_effect,
    required_sample_size,
    revenue_impact,
)

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "04-capstone-churn" / "reports"

# Assumptions. Every one of these is a guess that the design depends on, so they
# live here, named, instead of inline as bare numbers.
BASELINE_REACTIVATION = 0.06   # share of at-risk customers who return unprompted in 90 days
TARGET_LIFT = 0.03             # 6% -> 9%: the smallest lift worth the campaign's cost
ALPHA = 0.05
POWER = 0.80
CONTROL_SHARE = 0.30           # hold back 30%, not 50%: see note in main()
EMAIL_COST_PER_CUSTOMER = 12.0  # naira, blended send + creative amortisation


def active_base_size(con) -> int:
    """The full churn-eligible active base, which is what the model can score.

    The RFM bucket is a hand-drawn segment; the model scores everyone. Swapping
    the bucket for the score is the lever that buys sample size, and the cost is
    that the targeted group is less concentrated in high-value customers.
    """
    sql = (ROOT / "04-capstone-churn" / "sql" / "churn_features.sql").read_text()
    con.execute(sql.replace("{{CUTOFF_OFFSET_DAYS}}", "90"))
    return int(con.execute("SELECT count(*) FROM churn_features").fetchone()[0])


def evaluate_design(label: str, population: int, control_share: float,
                    n_needed: int) -> dict:
    """Is this design powered, and if not, what can it actually detect?"""
    control_n = int(population * control_share)
    treatment_n = population - control_n
    smaller_arm = min(control_n, treatment_n)
    return {
        "label": label,
        "population": population,
        "control_share": control_share,
        "treatment_n": treatment_n,
        "control_n": control_n,
        "smaller_arm": smaller_arm,
        "powered": smaller_arm >= n_needed,
        "mde": minimum_detectable_effect(BASELINE_REACTIVATION, smaller_arm, ALPHA, POWER),
    }


def segment_sizes(con) -> dict:
    """How many customers are actually targetable, and what are they worth."""
    row = con.execute("""
        SELECT
            count(*)                                   AS at_risk_customers,
            round(avg(monetary))                       AS avg_lifetime_revenue,
            round(avg(frequency), 2)                   AS avg_orders,
            round(avg(recency_days))                   AS avg_days_since_order
        FROM q5_rfm_segments
        WHERE segment = 'at risk - was loyal'
    """).fetchone()
    aov = con.execute("""
        SELECT round(sum(net_revenue) / count(*)) FROM analysis_orders
    """).fetchone()[0]
    return {
        "at_risk_customers": int(row[0]),
        "avg_lifetime_revenue": float(row[1]),
        "avg_orders": float(row[2]),
        "avg_days_since_order": float(row[3]),
        "average_order_value": float(aov),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="warehouse.duckdb", type=Path)
    args = ap.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(args.db), read_only=False)
    con.execute((ROOT / "01-sql-retail-warehouse" / "sql" / "01_staging.sql").read_text())
    con.execute((ROOT / "01-sql-retail-warehouse" / "sql" / "02_analysis.sql").read_text())

    seg = segment_sizes(con)
    print("Targetable segment (RFM 'at risk - was loyal')")
    print(f"  customers                 {seg['at_risk_customers']:,}")
    print(f"  average lifetime revenue  {seg['avg_lifetime_revenue']:,.0f}")
    print(f"  average orders            {seg['avg_orders']}")
    print(f"  days since last order     {seg['avg_days_since_order']:.0f}")
    print(f"  business-wide AOV         {seg['average_order_value']:,.0f}")

    # --- Design -------------------------------------------------------------
    n_needed = required_sample_size(BASELINE_REACTIVATION, TARGET_LIFT, ALPHA, POWER)
    total_needed = n_needed * 2
    print(f"\nTo detect {BASELINE_REACTIVATION:.0%} -> "
          f"{BASELINE_REACTIVATION + TARGET_LIFT:.0%} reactivation "
          f"at {POWER:.0%} power, alpha={ALPHA}:")
    print(f"  required per arm          {n_needed:,}")
    print(f"  required in total         {total_needed:,}")

    available = seg["at_risk_customers"]
    control_n = int(available * CONTROL_SHARE)
    treatment_n = available - control_n
    feasible = min(control_n, treatment_n) >= n_needed

    print(f"\nAvailable: {available:,} customers "
          f"({treatment_n:,} treatment / {control_n:,} control at a "
          f"{CONTROL_SHARE:.0%} holdback)")
    print(f"  powered for the target lift? {'YES' if feasible else 'NO'}")

    mde_control = minimum_detectable_effect(BASELINE_REACTIVATION, control_n, ALPHA, POWER)
    print(f"  smallest detectable lift with this segment: "
          f"{mde_control:.2%} ({mde_control / BASELINE_REACTIVATION:.0%} relative)")

    # --- The segment is too small. Evaluate the alternatives numerically. ---
    active_n = active_base_size(con)
    options = [
        evaluate_design("RFM 'at risk' bucket, 30% holdback", available, 0.30, n_needed),
        evaluate_design("RFM 'at risk' bucket, 50% holdback", available, 0.50, n_needed),
        evaluate_design("model-scored active base, 30% holdback", active_n, 0.30, n_needed),
        evaluate_design("model-scored active base, 50% holdback", active_n, 0.50, n_needed),
    ]
    print(f"\n--- Design options (need {n_needed:,} per arm) ---")
    print(f"{'option':<42}{'treat':>8}{'control':>9}{'MDE':>9}  powered")
    for o in options:
        mde = "n/a" if o["mde"] != o["mde"] else f"{o['mde']:.2%}"
        print(f"{o['label']:<42}{o['treatment_n']:>8,}{o['control_n']:>9,}"
              f"{mde:>9}  {'yes' if o['powered'] else 'NO'}")

    chosen = next((o for o in options if o["powered"]), None)
    if chosen is None:
        print("\n  Nothing available is powered for the target lift. Run for longer,")
        print("  accumulate newly-lapsing customers, or state the larger detectable")
        print("  effect up front. What is NOT acceptable is running it underpowered")
        print("  and reporting 'no significant effect' as if it meant 'no effect'.")
    else:
        print(f"\n  Recommended: {chosen['label']}")
        print("  A 50/50 split is used rather than the usual 70/30 because the")
        print("  binding constraint is the SMALLER arm. Power is driven by the")
        print("  smaller arm, so an uneven split wastes the population: 30% of")
        print(f"  {chosen['population']:,} is only {int(chosen['population'] * 0.3):,},")
        print(f"  below the {n_needed:,} needed, while 50% is {chosen['control_n']:,}.")
        print("  The cost of widening from the RFM bucket to the full scored base")
        print("  is precision: the targeted group is less concentrated in")
        print("  high-value customers, so the revenue per reactivation falls.")

    # --- A worked analysis of a plausible outcome ---------------------------
    # Not a result. A rehearsal, so that the analysis plan is written and agreed
    # before any data arrives and nobody gets to choose the method after seeing
    # the numbers.
    design = chosen or options[0]
    d_control_n, d_treatment_n = design["control_n"], design["treatment_n"]
    sim_control_conv = round(d_control_n * BASELINE_REACTIVATION)
    sim_treat_conv = round(d_treatment_n * (BASELINE_REACTIVATION + TARGET_LIFT))
    result = analyse_two_proportions(
        d_control_n, sim_control_conv, d_treatment_n, sim_treat_conv
    )
    print(f"\n  (rehearsed on the recommended design: {design['label']})")
    print("\n--- Pre-registered analysis, rehearsed on the hypothesised outcome ---")
    print(result.summary())

    impact = revenue_impact(
        result,
        annual_population=design["population"],
        average_order_value=seg["average_order_value"],
        extra_assumptions=(
            "A reactivated customer places exactly one order in the window.",
            f"Campaign cost of {EMAIL_COST_PER_CUSTOMER:,.0f} per contacted "
            f"customer is excluded from the gross figure below.",
        ),
    )
    campaign_cost = d_treatment_n * EMAIL_COST_PER_CUSTOMER
    print("\n--- If that outcome occurred ---")
    print(impact.summary())
    print(f"\n  gross revenue (point)   {impact.point_estimate:>14,.0f}")
    print(f"  campaign cost           {campaign_cost:>14,.0f}")
    print(f"  net (point)             {impact.point_estimate - campaign_cost:>14,.0f}")
    print(f"  net at the lower bound  {impact.low_estimate - campaign_cost:>14,.0f}")
    print(f"  breakeven lift          "
          f"{campaign_cost / (design['population'] * seg['average_order_value']):>14.2%}")

    out = {
        "segment": seg,
        "assumptions": {
            "baseline_reactivation": BASELINE_REACTIVATION,
            "target_lift": TARGET_LIFT,
            "alpha": ALPHA,
            "power": POWER,
            "control_share": CONTROL_SHARE,
            "email_cost_per_customer": EMAIL_COST_PER_CUSTOMER,
        },
        "design": {
            "required_per_arm": n_needed,
            "required_total": total_needed,
            "rfm_segment_available": available,
            "model_scored_active_base": active_n,
            "rfm_bucket_30pct_holdback_powered": feasible,
            "rfm_bucket_mde": mde_control,
            "options": [dict(o) for o in options],
            "recommended": design["label"],
            "recommended_treatment_n": d_treatment_n,
            "recommended_control_n": d_control_n,
        },
        "rehearsed_outcome": {
            "absolute_lift": result.absolute_lift,
            "relative_lift": result.relative_lift,
            "p_value": result.p_value,
            "ci": [result.ci_low, result.ci_high],
            "gross_revenue_point": impact.point_estimate,
            "gross_revenue_low": impact.low_estimate,
            "gross_revenue_high": impact.high_estimate,
            "campaign_cost": campaign_cost,
            "net_point": impact.point_estimate - campaign_cost,
            "net_low": impact.low_estimate - campaign_cost,
            "breakeven_lift": campaign_cost / (design["population"] * seg["average_order_value"]),
        },
    }
    (REPORTS / "experiment_design.json").write_text(json.dumps(out, indent=2))
    print(f"\nWrote {REPORTS / 'experiment_design.json'}")


if __name__ == "__main__":
    main()
