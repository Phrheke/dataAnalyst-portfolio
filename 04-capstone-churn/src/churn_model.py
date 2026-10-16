"""Train and validate a churn model, out of time.

The headline choice here is the validation scheme. A random train/test split on
a churn snapshot leaks: the rows are not independent draws, they are one
photograph of one customer base at one moment, and a model tuned on a random
half of it will look better than it is. So this trains on a snapshot taken six
months earlier and tests on the current one. The gap between the random-split
score and the out-of-time score is reported, because that gap is the honest
measure of how much the easier number was flattering itself.

Outputs (written to 04-capstone-churn/reports/):
    model_metrics.json     every number quoted in the decision memo
    decile_lift.csv        the table the retention team actually uses
    coefficients.csv       logistic regression coefficients, standardised
    roc_pr_curves.png      ROC and precision-recall, both snapshots
    calibration.png        predicted versus observed churn rate

Usage:
    python 04-capstone-churn/src/churn_model.py --db warehouse.duckdb
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[2]
SQL_STAGING = ROOT / "01-sql-retail-warehouse" / "sql" / "01_staging.sql"
SQL_FEATURES = ROOT / "04-capstone-churn" / "sql" / "churn_features.sql"
REPORTS = ROOT / "04-capstone-churn" / "reports"

TRAIN_OFFSET_DAYS = 270   # snapshot six months before the test snapshot
TEST_OFFSET_DAYS = 90     # the most recent snapshot with a complete label window

CATEGORICAL = ["acquisition_channel", "country_filled"]
DROP = ["customer_id", "churned"]
SEED = 42


def load_snapshot(con, offset_days: int) -> pd.DataFrame:
    """Materialise the feature table at a given cutoff offset."""
    sql = SQL_FEATURES.read_text().replace("{{CUTOFF_OFFSET_DAYS}}", str(offset_days))
    con.execute(sql)
    cutoff = con.execute("SELECT cutoff FROM churn_config").fetchone()[0]
    df = con.execute("SELECT * FROM churn_features").df()
    df.attrs["cutoff"] = str(cutoff)
    df.attrs["offset_days"] = offset_days
    return df


def build_pipeline(numeric: list[str], categorical: list[str], kind: str) -> Pipeline:
    """A pipeline, not a bare estimator.

    Imputation and scaling are fitted inside cross-validation folds. Computing
    a mean or a scale on the full dataset before splitting is the quietest form
    of leakage there is, and it is the default if you reach for
    `df.fillna(df.mean())` first.
    """
    numeric_steps = Pipeline([
        # overdue_ratio is null for single-order customers, who have no gap
        # history. The median is a defensible fill and the indicator column
        # preserves the fact that it was missing, which is itself predictive.
        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", StandardScaler()),
    ])
    pre = ColumnTransformer([
        ("num", numeric_steps, numeric),
        ("cat", OneHotEncoder(handle_unknown="ignore", drop="first"), categorical),
    ])

    if kind == "logistic":
        model = LogisticRegression(max_iter=2000, C=1.0, random_state=SEED)
    elif kind == "gbm":
        model = HistGradientBoostingClassifier(
            max_depth=3, max_iter=250, learning_rate=0.06,
            l2_regularization=1.0, random_state=SEED,
        )
    elif kind == "baseline":
        model = DummyClassifier(strategy="prior")
    else:
        raise ValueError(kind)

    return Pipeline([("pre", pre), ("model", model)])


def decile_lift(y_true: np.ndarray, y_prob: np.ndarray) -> pd.DataFrame:
    """Churn rate by predicted-risk decile.

    This is the only output of the whole model that a retention manager will
    ever look at. ROC AUC answers "is the ranking any good"; this answers "if I
    can only email 10% of the base, how much better than random is that 10%".
    """
    df = pd.DataFrame({"y": y_true, "p": y_prob})
    # rank-based deciles, so ties in probability do not collapse a decile
    df["decile"] = pd.qcut(df["p"].rank(method="first"), 10, labels=range(1, 11))
    out = (
        df.groupby("decile", observed=True)
        .agg(customers=("y", "size"), churned=("y", "sum"),
             mean_predicted=("p", "mean"))
        .assign(
            observed_rate=lambda d: d["churned"] / d["customers"],
            overall_rate=lambda d: df["y"].mean(),
        )
    )
    out["lift"] = out["observed_rate"] / out["overall_rate"]
    out = out.sort_index(ascending=False)
    out["cumulative_churners_captured"] = out["churned"].cumsum()
    out["pct_of_all_churners"] = 100 * out["cumulative_churners_captured"] / df["y"].sum()
    out["pct_of_base_contacted"] = 100 * out["customers"].cumsum() / len(df)
    return out.reset_index()


def max_achievable_lift(base_rate: float, decile_share: float = 0.10) -> float:
    """The best top-decile lift any model could possibly achieve.

    If the base churn rate is p, a perfect ranking puts churners first, so the
    top decile is 100% churners whenever p >= decile_share, giving lift = 1/p.
    This ceiling matters: at a 57% base rate the maximum possible lift is 1.74x,
    so a 1.50x result is 86% of perfect, not the mediocre number it looks like
    next to the 5x-10x lifts quoted for rare-event churn problems. Comparing raw
    lift across problems with different base rates is meaningless.
    """
    if base_rate <= 0:
        return float("nan")
    if base_rate >= decile_share:
        return 1.0 / base_rate
    return 1.0 / decile_share


def collinearity_report(df: pd.DataFrame, numeric: list[str], threshold: float = 0.8):
    """Pairs of features correlated strongly enough to scramble coefficient signs.

    Logistic regression coefficients in the presence of near-duplicate features
    are not interpretable as effects: the fit distributes the shared signal
    between them arbitrarily, and one can land with the wrong sign entirely.
    This surfaces the pairs responsible so that the write-up can say so instead
    of confidently misreading its own model.
    """
    corr = df[numeric].corr().abs()
    pairs = []
    for i, a in enumerate(numeric):
        for b in numeric[i + 1:]:
            r = corr.loc[a, b]
            if pd.notna(r) and r >= threshold:
                pairs.append({"feature_a": a, "feature_b": b,
                              "abs_correlation": round(float(r), 3)})
    return pd.DataFrame(pairs).sort_values("abs_correlation", ascending=False) if pairs \
        else pd.DataFrame(columns=["feature_a", "feature_b", "abs_correlation"])


def univariate_direction(df: pd.DataFrame, numeric: list[str], target: str = "churned"):
    """Each feature's raw relationship with churn, independent of the model.

    Computed as the churn rate in the top versus the bottom tercile. Comparing
    this against the fitted coefficient catches sign flips caused by
    collinearity -- the single most common way a model gets misreported.
    """
    rows = []
    for f in numeric:
        col = df[f]
        if col.nunique() < 3:
            continue
        try:
            terciles = pd.qcut(col.rank(method="first"), 3, labels=["low", "mid", "high"])
        except ValueError:
            continue
        g = df.groupby(terciles, observed=True)[target].mean()
        if "low" not in g or "high" not in g:
            continue
        rows.append({
            "feature": f,
            "churn_rate_low_tercile": round(float(g["low"]), 4),
            "churn_rate_high_tercile": round(float(g["high"]), 4),
            "univariate_direction": "increases churn" if g["high"] > g["low"] else "reduces churn",
        })
    return pd.DataFrame(rows)


def evaluate(name: str, pipe: Pipeline, X_tr, y_tr, X_te, y_te) -> dict:
    pipe.fit(X_tr, y_tr)
    prob = pipe.predict_proba(X_te)[:, 1]
    return {
        "model": name,
        "roc_auc": float(roc_auc_score(y_te, prob)),
        "pr_auc": float(average_precision_score(y_te, prob)),
        "brier": float(brier_score_loss(y_te, prob)),
        "test_churn_rate": float(np.mean(y_te)),
        "n_train": int(len(y_tr)),
        "n_test": int(len(y_te)),
        "_prob": prob,
        "_pipe": pipe,
    }


def plot_curves(results: dict, y_te, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.6))
    for name, r in results.items():
        if name == "baseline":
            continue
        fpr, tpr, _ = roc_curve(y_te, r["_prob"])
        ax1.plot(fpr, tpr, label=f"{name} (AUC {r['roc_auc']:.3f})")
        prec, rec, _ = precision_recall_curve(y_te, r["_prob"])
        ax2.plot(rec, prec, label=f"{name} (AP {r['pr_auc']:.3f})")

    ax1.plot([0, 1], [0, 1], "k--", lw=1, label="random")
    ax1.set(xlabel="False positive rate", ylabel="True positive rate",
            title="ROC — out-of-time test set")
    ax1.legend(frameon=False, fontsize=9)

    base = float(np.mean(y_te))
    ax2.axhline(base, ls="--", c="k", lw=1, label=f"base rate {base:.2f}")
    ax2.set(xlabel="Recall", ylabel="Precision",
            title="Precision–recall — out-of-time test set")
    ax2.legend(frameon=False, fontsize=9)

    for ax in (ax1, ax2):
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_calibration(results: dict, y_te, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5.6, 5))
    for name, r in results.items():
        if name == "baseline":
            continue
        df = pd.DataFrame({"y": y_te, "p": r["_prob"]})
        df["bin"] = pd.qcut(df["p"].rank(method="first"), 10, labels=False)
        g = df.groupby("bin").agg(pred=("p", "mean"), obs=("y", "mean"))
        ax.plot(g["pred"], g["obs"], "o-", label=f"{name} (Brier {r['brier']:.3f})")
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect calibration")
    ax.set(xlabel="Mean predicted probability", ylabel="Observed churn rate",
           title="Calibration — out-of-time test set")
    ax.legend(frameon=False, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="warehouse.duckdb", type=Path)
    args = ap.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(args.db))
    con.execute(SQL_STAGING.read_text())

    train = load_snapshot(con, TRAIN_OFFSET_DAYS)
    test = load_snapshot(con, TEST_OFFSET_DAYS)
    print(f"train snapshot  cutoff {train.attrs['cutoff'][:10]}  "
          f"n={len(train):,}  churn={train['churned'].mean():.1%}")
    print(f"test  snapshot  cutoff {test.attrs['cutoff'][:10]}  "
          f"n={len(test):,}  churn={test['churned'].mean():.1%}")

    features = [c for c in train.columns if c not in DROP]
    numeric = [c for c in features if c not in CATEGORICAL]
    # Booleans must be numeric for the scaler.
    for df in (train, test):
        for c in df.columns:
            if df[c].dtype == bool:
                df[c] = df[c].astype(int)

    X_tr, y_tr = train[features], train["churned"].to_numpy()
    X_te, y_te = test[features], test["churned"].to_numpy()

    results = {}
    for kind in ("baseline", "logistic", "gbm"):
        results[kind] = evaluate(kind, build_pipeline(numeric, CATEGORICAL, kind),
                                 X_tr, y_tr, X_te, y_te)
        r = results[kind]
        print(f"  {kind:<9} out-of-time ROC AUC {r['roc_auc']:.3f}   "
              f"PR AUC {r['pr_auc']:.3f}   Brier {r['brier']:.3f}")

    # The optimistic number, for contrast: a random split within the test
    # snapshot, which is what most churn write-ups report.
    Xa, Xb, ya, yb = train_test_split(
        X_te, y_te, test_size=0.3, random_state=SEED, stratify=y_te
    )
    optimistic = evaluate("logistic (random split)",
                          build_pipeline(numeric, CATEGORICAL, "logistic"),
                          Xa, ya, Xb, yb)
    cv = cross_val_score(
        build_pipeline(numeric, CATEGORICAL, "logistic"), X_te, y_te,
        cv=StratifiedKFold(5, shuffle=True, random_state=SEED), scoring="roc_auc",
    )
    print(f"\n  random split within test snapshot : ROC AUC {optimistic['roc_auc']:.3f}")
    print(f"  5-fold CV within test snapshot    : ROC AUC {cv.mean():.3f} "
          f"(+/- {cv.std():.3f})")
    print(f"  honest out-of-time                : ROC AUC {results['logistic']['roc_auc']:.3f}")
    print(f"  optimism from in-snapshot validation: "
          f"{cv.mean() - results['logistic']['roc_auc']:+.3f} AUC")

    best_name = max(("logistic", "gbm"), key=lambda k: results[k]["roc_auc"])
    best = results[best_name]

    lift = decile_lift(y_te, best["_prob"])
    lift.to_csv(REPORTS / "decile_lift.csv", index=False)
    base_rate = float(np.mean(y_te))
    ceiling = max_achievable_lift(base_rate)
    achieved = float(lift.iloc[0]["lift"])
    print(f"\nTop-decile lift ({best_name}): {achieved:.2f}x  "
          f"-- contacting 10% of the base reaches "
          f"{lift.iloc[0]['pct_of_all_churners']:.0f}% of churners")
    print(f"  ceiling at a {base_rate:.1%} base rate is {ceiling:.2f}x, "
          f"so this is {achieved / ceiling:.0%} of the best any model could do")

    # Standardised logistic coefficients. Because the scaler ran first, these
    # are comparable to each other: one standard deviation of each feature.
    log_pipe = results["logistic"]["_pipe"]
    names = log_pipe.named_steps["pre"].get_feature_names_out()
    coefs = log_pipe.named_steps["model"].coef_[0]
    coef_df = (
        pd.DataFrame({"feature": names, "coefficient": coefs})
        .assign(odds_ratio=lambda d: np.exp(d["coefficient"]),
                abs_coef=lambda d: d["coefficient"].abs())
        .sort_values("abs_coef", ascending=False)
        .drop(columns="abs_coef")
    )
    coef_df.to_csv(REPORTS / "coefficients.csv", index=False)
    print("\nStrongest standardised coefficients:")
    print(coef_df.head(8).to_string(index=False, float_format=lambda v: f"{v:8.3f}"))

    collin = collinearity_report(test[numeric], numeric)
    collin.to_csv(REPORTS / "collinearity.csv", index=False)
    uni = univariate_direction(test, numeric)
    uni.to_csv(REPORTS / "univariate_direction.csv", index=False)

    # Flag any feature whose fitted coefficient disagrees with its raw
    # relationship to churn. These are the coefficients that must NOT be quoted
    # as effects in the write-up.
    sign_flips = []
    uni_map = dict(zip(uni["feature"], uni["univariate_direction"], strict=True))
    for _, row in coef_df.iterrows():
        feat = row["feature"]
        if not feat.startswith("num__"):
            continue
        raw = feat[len("num__"):]
        direction = uni_map.get(raw)
        if direction is None:
            continue
        model_dir = "increases churn" if row["coefficient"] > 0 else "reduces churn"
        if model_dir != direction and abs(row["coefficient"]) > 0.1:
            sign_flips.append({"feature": raw, "model_says": model_dir,
                               "data_says": direction,
                               "coefficient": round(float(row["coefficient"]), 3)})
    if sign_flips:
        print("\nSIGN FLIPS -- do not interpret these coefficients as effects:")
        for f in sign_flips:
            print(f"  {f['feature']:<24} model: {f['model_says']:<16} "
                  f"data: {f['data_says']}  (coef {f['coefficient']:+.3f})")
        if not collin.empty:
            print(f"  likely cause: {len(collin)} feature pairs with |r| >= 0.8 "
                  f"(see reports/collinearity.csv)")

    plot_curves(results, y_te, REPORTS / "roc_pr_curves.png")
    plot_calibration(results, y_te, REPORTS / "calibration.png")

    metrics = {
        "train_snapshot": {"cutoff": train.attrs["cutoff"], "n": len(train),
                           "churn_rate": float(train["churned"].mean())},
        "test_snapshot": {"cutoff": test.attrs["cutoff"], "n": len(test),
                          "churn_rate": float(test["churned"].mean())},
        "out_of_time": {k: {m: v[m] for m in ("roc_auc", "pr_auc", "brier")}
                        for k, v in results.items()},
        "in_snapshot_random_split_roc_auc": optimistic["roc_auc"],
        "in_snapshot_cv_roc_auc_mean": float(cv.mean()),
        "in_snapshot_cv_roc_auc_std": float(cv.std()),
        "optimism_auc": float(cv.mean() - results["logistic"]["roc_auc"]),
        "best_model": best_name,
        "top_decile_lift": achieved,
        "top_decile_lift_ceiling": ceiling,
        "top_decile_pct_of_ceiling": achieved / ceiling,
        "top_decile_pct_of_churners": float(lift.iloc[0]["pct_of_all_churners"]),
        "n_features": len(features),
        "collinear_pairs_over_0.8": int(len(collin)),
        "coefficient_sign_flips": sign_flips,
    }
    (REPORTS / "model_metrics.json").write_text(json.dumps(metrics, indent=2))
    print(f"\nWrote {REPORTS}/model_metrics.json and 3 other artefacts")


if __name__ == "__main__":
    main()
