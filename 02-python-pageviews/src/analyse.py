"""Does interest in professional topics follow the working week?

The question: Wikipedia pageviews for data-analysis topics should dip at the
weekend if people read them at work, and leisure topics should not. How large is
the gap, and is it distinguishable from noise?

The methodological point this project is really about: **daily pageviews are
heavily autocorrelated, so a two-sample test on individual days is
pseudo-replication.** It treats 1,095 correlated observations as 1,095
independent ones and produces a p-value that is far too small. The analysis
below runs the naive test first, then the paired weekly test, and reports how
much the naive version overstates its own confidence.

Outputs (to reports/):
    findings.json          every number quoted in the write-up
    weekday_profile.png    mean views by day of week, per topic class
    series.png             the raw series, so the reader can see the data
    effect_sizes.png       weekend effect with bootstrap intervals

Usage:
    python 02-python-pageviews/src/analyse.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
REPORTS = PROJECT / "reports"

HOLIDAYS = {
    (1, 1), (12, 24), (12, 25), (12, 26), (12, 31),
    (7, 4), (11, 28), (11, 27),
}
BOOTSTRAP_N = 5000
SEED = 42


# -----------------------------------------------------------------------------
# Load and clean
# -----------------------------------------------------------------------------

def load(data_dir: Path) -> tuple[pd.DataFrame, dict]:
    path = data_dir / "pageviews.csv"
    if not path.exists():
        raise SystemExit(
            f"{path} not found.\n"
            "Run one of:\n"
            "  python 02-python-pageviews/src/collect.py          (real API data)\n"
            "  python 02-python-pageviews/src/simulate_offline.py (offline fixture)"
        )

    df = pd.read_csv(path, parse_dates=["date"])
    expected = {"article", "topic_class", "date", "views"}
    missing = expected - set(df.columns)
    if missing:
        raise SystemExit(f"{path} is missing columns: {sorted(missing)}")

    prov_path = data_dir / "provenance.json"
    source = {
        "is_real_api_data": prov_path.exists(),
        "provenance": json.loads(prov_path.read_text()) if prov_path.exists() else None,
    }

    df["weekday"] = df["date"].dt.dayofweek
    df["day_name"] = df["date"].dt.day_name()
    df["is_weekend"] = df["weekday"] >= 5
    df["iso_year"] = df["date"].dt.isocalendar().year
    df["iso_week"] = df["date"].dt.isocalendar().week
    df["is_holiday"] = [(d.month, d.day) in HOLIDAYS for d in df["date"]]
    return df, source


def quality_report(df: pd.DataFrame) -> dict:
    """What is wrong with the data, counted rather than assumed."""
    per_article = []
    for article, g in df.groupby("article"):
        span = (g["date"].max() - g["date"].min()).days + 1
        # Outliers by the robust rule: a spike is more than 5 MADs above the
        # median. The standard deviation is useless here because the spikes
        # themselves inflate it.
        med = g["views"].median()
        mad = stats.median_abs_deviation(g["views"], scale="normal")
        spikes = int((g["views"] > med + 5 * mad).sum()) if mad > 0 else 0
        per_article.append({
            "article": article,
            "days_present": int(len(g)),
            "days_in_span": int(span),
            "missing_days": int(span - len(g)),
            "pct_missing": round(100 * (span - len(g)) / span, 2),
            "median_views": int(med),
            "spike_days": spikes,
            "zero_days": int((g["views"] == 0).sum()),
        })
    return {
        "rows": int(len(df)),
        "articles": int(df["article"].nunique()),
        "date_min": df["date"].min().date().isoformat(),
        "date_max": df["date"].max().date().isoformat(),
        "total_missing_days": int(sum(a["missing_days"] for a in per_article)),
        "total_spike_days": int(sum(a["spike_days"] for a in per_article)),
        "per_article": per_article,
    }


# -----------------------------------------------------------------------------
# The two tests
# -----------------------------------------------------------------------------

def naive_test(g: pd.DataFrame) -> dict:
    """Welch's t-test on individual days. Deliberately wrong, shown for contrast.

    Every day is treated as an independent observation. They are not: today's
    pageviews predict tomorrow's, so the effective sample size is far smaller
    than the row count and the p-value is correspondingly far too small.
    """
    wd = g.loc[~g["is_weekend"], "views"]
    we = g.loc[g["is_weekend"], "views"]
    t_stat, p = stats.ttest_ind(we, wd, equal_var=False)
    return {
        "test": "Welch t-test on individual days (pseudo-replication)",
        "n_weekday_days": int(len(wd)),
        "n_weekend_days": int(len(we)),
        "effective_n": int(len(wd) + len(we)),
        "t": float(t_stat),
        "p_value": float(p),
    }


def paired_weekly_test(g: pd.DataFrame) -> dict:
    """Paired test on the weekly weekend/weekday ratio. The defensible one.

    For each ISO week, take the mean weekday views and the mean weekend views,
    and form the ratio. Pairing within a week removes the secular trend and the
    seasonality, because both arms of each pair come from the same seven days.
    One observation per week also respects the autocorrelation: weeks are far
    closer to independent than days are.

    The statistic is the log ratio, tested against zero. Logs because the ratio
    is bounded below by zero and right-skewed, so its distribution is much
    closer to normal on the log scale -- and because the mean of log ratios
    back-transforms to a geometric mean, which is the right average for a
    multiplicative quantity.
    """
    weekly = (
        g.groupby(["iso_year", "iso_week", "is_weekend"])["views"]
        .mean()
        .unstack("is_weekend")
    )
    weekly.columns = ["weekday_mean", "weekend_mean"]
    weekly = weekly.dropna()
    weekly = weekly[(weekly["weekday_mean"] > 0) & (weekly["weekend_mean"] > 0)]

    log_ratio = np.log(weekly["weekend_mean"] / weekly["weekday_mean"])
    t_stat, p = stats.ttest_1samp(log_ratio, 0.0)
    # Wilcoxon as a distribution-free cross-check. If the two disagree, the
    # normality assumption is doing more work than it should.
    try:
        _, p_wilcoxon = stats.wilcoxon(log_ratio)
    except ValueError:
        p_wilcoxon = float("nan")

    mean_log = float(log_ratio.mean())
    se = float(log_ratio.std(ddof=1) / np.sqrt(len(log_ratio)))
    crit = stats.t.ppf(0.975, df=len(log_ratio) - 1)

    return {
        "test": "paired t-test on weekly log(weekend/weekday) ratio",
        "n_weeks": int(len(log_ratio)),
        "t": float(t_stat),
        "p_value": float(p),
        "p_value_wilcoxon": float(p_wilcoxon),
        "geometric_mean_ratio": float(np.exp(mean_log)),
        "ratio_ci_low": float(np.exp(mean_log - crit * se)),
        "ratio_ci_high": float(np.exp(mean_log + crit * se)),
        "weekend_effect_pct": float((np.exp(mean_log) - 1) * 100),
        "weekend_effect_pct_ci": [
            float((np.exp(mean_log - crit * se) - 1) * 100),
            float((np.exp(mean_log + crit * se) - 1) * 100),
        ],
        "cohens_d": float(mean_log / log_ratio.std(ddof=1)),
    }


def autocorrelation(g: pd.DataFrame) -> dict:
    """Lag-1 and lag-7 autocorrelation, to justify the paired design.

    Lag-7 is the weekly cycle itself. Lag-1 on a weekday-only series is the
    number that shows the days are not independent.
    """
    s = g.sort_values("date").set_index("date")["views"].asfreq("D")
    weekday_only = s[s.index.dayofweek < 5].dropna()
    return {
        "lag1_all_days": float(s.dropna().autocorr(lag=1)),
        "lag7_all_days": float(s.dropna().autocorr(lag=7)),
        "lag1_weekday_only": float(weekday_only.autocorr(lag=1)),
    }


def bootstrap_ratio_ci(g: pd.DataFrame, rng) -> tuple[float, float]:
    """Block bootstrap over whole weeks, resampling the paired ratios.

    Resampling individual days would destroy the week structure and understate
    the uncertainty. Resampling whole weeks preserves it.
    """
    weekly = (
        g.groupby(["iso_year", "iso_week", "is_weekend"])["views"]
        .mean().unstack("is_weekend").dropna()
    )
    weekly.columns = ["weekday_mean", "weekend_mean"]
    weekly = weekly[(weekly["weekday_mean"] > 0) & (weekly["weekend_mean"] > 0)]
    ratios = (weekly["weekend_mean"] / weekly["weekday_mean"]).to_numpy()
    if len(ratios) < 5:
        return float("nan"), float("nan")
    draws = rng.choice(ratios, size=(BOOTSTRAP_N, len(ratios)), replace=True)
    geo_means = np.exp(np.log(draws).mean(axis=1))
    return float(np.percentile(geo_means, 2.5)), float(np.percentile(geo_means, 97.5))


# -----------------------------------------------------------------------------
# Sensitivity
# -----------------------------------------------------------------------------

def sensitivity(g: pd.DataFrame) -> dict:
    """Does the conclusion survive the choices I made while cleaning?

    Four variants. If the headline moves materially under any of them, the
    headline was an artefact of a cleaning decision rather than a finding, and
    the write-up has to say so.
    """
    med = g["views"].median()
    mad = stats.median_abs_deviation(g["views"], scale="normal")

    variants = {
        "headline (all data)": g,
        "holidays excluded": g[~g["is_holiday"]],
        "spikes excluded (>5 MAD)": g[g["views"] <= med + 5 * mad] if mad > 0 else g,
        "2025 only": g[g["date"].dt.year == 2025],
        "Mon-Thu vs Sat-Sun (drop Friday)": g[g["weekday"] != 4],
    }
    out = {}
    for name, sub in variants.items():
        if sub.empty or sub["is_weekend"].nunique() < 2:
            continue
        r = paired_weekly_test(sub)
        out[name] = {
            "weekend_effect_pct": round(r["weekend_effect_pct"], 2),
            "ci": [round(r["weekend_effect_pct_ci"][0], 2),
                   round(r["weekend_effect_pct_ci"][1], 2)],
            "p_value": r["p_value"],
            "n_weeks": r["n_weeks"],
        }
    return out


# -----------------------------------------------------------------------------
# Charts
# -----------------------------------------------------------------------------

def make_charts(df: pd.DataFrame, per_article: dict, is_real: bool) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    note = "" if is_real else "  [SIMULATED FIXTURE — not real Wikipedia data]"
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    colours = {"professional": "#2b6cb0", "tooling": "#2f855a", "leisure": "#b7791f"}

    # 1. Weekday profile, indexed so articles of different sizes are comparable.
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    for topic_class, g in df.groupby("topic_class"):
        profile = g.groupby("day_name")["views"].mean().reindex(order)
        indexed = 100 * profile / profile[:5].mean()
        ax.plot(order, indexed, "o-", label=topic_class,
                color=colours.get(topic_class), lw=2)
    ax.axhline(100, ls="--", c="#999", lw=1)
    ax.set(ylabel="Views, indexed to Mon–Fri mean = 100",
           title=f"Weekday profile by topic class{note}")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(REPORTS / "weekday_profile.png", dpi=140)
    plt.close(fig)

    # 2. The raw series. Always show the data, not only the summary.
    fig, axes = plt.subplots(3, 1, figsize=(10, 7.5), sharex=True)
    for ax, (topic_class, g) in zip(axes, df.groupby("topic_class"), strict=False):
        for article, ga in g.groupby("article"):
            weekly = ga.set_index("date")["views"].resample("W").mean()
            ax.plot(weekly.index, weekly.values, lw=1.2,
                    label=article.replace("_", " ")[:28])
        ax.set_title(topic_class, loc="left", fontsize=10)
        ax.legend(frameon=False, fontsize=7, ncol=3)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_title(f"Weekly mean pageviews{note}", loc="left", fontsize=11)
    axes[-1].set_xlabel("")
    fig.tight_layout()
    fig.savefig(REPORTS / "series.png", dpi=140)
    plt.close(fig)

    # 3. Effect sizes with intervals, sorted. The headline chart.
    fig, ax = plt.subplots(figsize=(8, 4.8))
    rows = sorted(per_article.items(), key=lambda kv: kv[1]["paired"]["weekend_effect_pct"])
    labels = [a.replace("_", " ")[:28] for a, _ in rows]
    effects = [v["paired"]["weekend_effect_pct"] for _, v in rows]
    los = [v["paired"]["weekend_effect_pct_ci"][0] for _, v in rows]
    his = [v["paired"]["weekend_effect_pct_ci"][1] for _, v in rows]
    cols = [colours.get(v["topic_class"], "#666") for _, v in rows]
    y = np.arange(len(rows))
    ax.hlines(y, los, his, color=cols, lw=3, alpha=0.45)
    ax.plot(effects, y, "o", color="white", markersize=9,
            markeredgewidth=2.2, markeredgecolor="#333", zorder=3)
    for yi, (e, c) in enumerate(zip(effects, cols, strict=True)):
        ax.plot(e, yi, "o", color=c, markersize=6, zorder=4)
    ax.axvline(0, c="#333", lw=1)
    ax.set_yticks(y, labels)
    ax.set(xlabel="Weekend effect on pageviews (%), 95% CI",
           title=f"Weekend effect by article{note}")
    ax.spines[["top", "right", "left"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(REPORTS / "effect_sizes.png", dpi=140)
    plt.close(fig)


# -----------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default=PROJECT / "data", type=Path)
    args = ap.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    df, source = load(args.data)

    print("=" * 74)
    print("SOURCE: " + ("real Wikimedia API data" if source["is_real_api_data"]
                        else "SIMULATED FIXTURE (run collect.py for real data)"))
    print("=" * 74)

    quality = quality_report(df)
    print(f"\n{quality['rows']:,} rows, {quality['articles']} articles, "
          f"{quality['date_min']} to {quality['date_max']}")
    print(f"missing days: {quality['total_missing_days']}   "
          f"spike days: {quality['total_spike_days']}")

    per_article = {}
    header = (f"\n{'article':<32}{'weekend effect':>16}{'95% CI':>20}"
              f"{'p (paired)':>12}{'p (naive)':>12}")
    print(header)
    print("-" * 92)
    for article, g in df.groupby("article"):
        paired = paired_weekly_test(g)
        naive = naive_test(g)
        acf = autocorrelation(g)
        boot_lo, boot_hi = bootstrap_ratio_ci(g, rng)
        per_article[article] = {
            "topic_class": g["topic_class"].iloc[0],
            "paired": paired,
            "naive": naive,
            "autocorrelation": acf,
            "bootstrap_ratio_ci": [boot_lo, boot_hi],
        }
        ci = paired["weekend_effect_pct_ci"]
        print(f"{article.replace('_',' ')[:30]:<32}"
              f"{paired['weekend_effect_pct']:>15.1f}%"
              f"{f'[{ci[0]:.1f}, {ci[1]:.1f}]':>20}"
              f"{paired['p_value']:>12.2e}{naive['p_value']:>12.2e}")

    # By topic class
    print(f"\n{'topic class':<18}{'weekend effect':>16}{'95% CI':>22}{'p':>12}")
    print("-" * 68)
    by_class = {}
    for topic_class, g in df.groupby("topic_class"):
        r = paired_weekly_test(g)
        by_class[topic_class] = r
        ci = r["weekend_effect_pct_ci"]
        print(f"{topic_class:<18}{r['weekend_effect_pct']:>15.1f}%"
              f"{f'[{ci[0]:.1f}, {ci[1]:.1f}]':>22}{r['p_value']:>12.2e}")

    # The methodological headline
    mean_lag1 = float(np.mean([v["autocorrelation"]["lag1_weekday_only"]
                               for v in per_article.values()]))
    print(f"\nLag-1 autocorrelation (weekdays only), mean across articles: {mean_lag1:.3f}")
    # Compare the two designs on the evidence rather than asserting a direction.
    # The naive test inflates confidence when the series is autocorrelated; how
    # much depends on how strong that correlation actually is, so measure it.
    inflation = []
    for v in per_article.values():
        p_naive, p_paired = v["naive"]["p_value"], v["paired"]["p_value"]
        if p_naive > 0 and p_paired > 0:
            inflation.append(np.log10(p_paired) - np.log10(p_naive))
    n_naive_smaller = sum(1 for v in per_article.values()
                          if v["naive"]["p_value"] < v["paired"]["p_value"])
    print(f"The naive day-level test reports a smaller p-value than the paired "
          f"weekly test\nfor {n_naive_smaller} of {len(per_article)} articles "
          f"(median difference {np.median(inflation):+.1f} orders of magnitude).")
    if mean_lag1 > 0.2:
        print("With lag-1 autocorrelation this high, the day-level test is "
              "pseudo-replication:\nit treats ~1,000 correlated days as "
              "independent observations.")
    else:
        print("Autocorrelation here is weak, so the two designs broadly agree. "
              "The paired\ndesign is still the right default: it removes trend "
              "and seasonality by construction.")

    sens = sensitivity(df[df["topic_class"] == "professional"])
    print("\nSensitivity — professional topics, weekend effect under different choices:")
    for name, r in sens.items():
        print(f"  {name:<36}{r['weekend_effect_pct']:>8.1f}%  "
              f"[{r['ci'][0]:.1f}, {r['ci'][1]:.1f}]  (n={r['n_weeks']} weeks)")

    make_charts(df, per_article, source["is_real_api_data"])

    findings = {
        "source": {"is_real_api_data": source["is_real_api_data"],
                   "provenance": source["provenance"]},
        "data_quality": quality,
        "by_article": per_article,
        "by_topic_class": by_class,
        "mean_lag1_autocorr_weekdays": mean_lag1,
        "naive_smaller_p_count": n_naive_smaller,
        "median_log10_p_difference": float(np.median(inflation)) if inflation else None,
        "sensitivity_professional": sens,
    }
    (REPORTS / "findings.json").write_text(json.dumps(findings, indent=2, default=str))
    print(f"\nWrote {REPORTS}/findings.json and 3 charts")


if __name__ == "__main__":
    main()
