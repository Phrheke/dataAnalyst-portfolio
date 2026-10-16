"""Generate a deterministic, deliberately messy e-commerce dataset.

Why synthetic: every project in this portfolio runs the moment you clone the
repo, with no credentials and no 2 GB download. Why messy: a clean dataset
hides the skill that actually gets analysts hired, which is deciding what to
do about bad rows and defending the decision.

The warts below are intentional and documented in
01-sql-retail-warehouse/data_quality/FINDINGS.md. Each one mirrors a failure
mode I have seen in real transactional data.

Usage:
    python src/generate_warehouse.py --out data/raw --seed 42
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

# --- Dimensions ------------------------------------------------------------

START = date(2024, 1, 1)
MONTHS = 24

COUNTRIES = ["NG", "GB", "US", "ZA", "KE", "GH", "CA", "DE"]
COUNTRY_W = [0.34, 0.14, 0.17, 0.09, 0.08, 0.06, 0.06, 0.06]

CHANNELS = ["organic", "paid_search", "paid_social", "email", "referral", "direct"]
CHANNEL_W = [0.26, 0.21, 0.19, 0.12, 0.08, 0.14]

DEVICES = ["mobile", "desktop", "tablet"]
DEVICE_W = [0.68, 0.27, 0.05]

CATEGORIES = {
    "skincare": (3200, 11500),
    "haircare": (2500, 9000),
    "fragrance": (6500, 28000),
    "makeup": (2800, 15000),
    "tools": (4500, 42000),
    "bundles": (9000, 55000),
}

# Status values are intentionally inconsistent in casing and vocabulary.
STATUS_RAW = ["completed", "Completed", "COMPLETED", "shipped",
              "cancelled", "Cancelled", "refunded", "pending"]
STATUS_W = [0.52, 0.12, 0.05, 0.13, 0.07, 0.03, 0.05, 0.03]


def _choice(rng, options, weights, size):
    return rng.choice(options, size=size, p=np.asarray(weights) / np.sum(weights))


def _month_starts():
    out = []
    y, m = START.year, START.month
    for _ in range(MONTHS):
        out.append(date(y, m, 1))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def build(seed: int):
    rng = np.random.default_rng(seed)
    months = _month_starts()

    # ---- customers --------------------------------------------------------
    n_cust = 12000
    # Signups grow over the two years, so cohorts have different sizes. A flat
    # signup curve makes retention charts look suspiciously tidy.
    weights = np.linspace(1.0, 2.6, MONTHS)
    weights = weights / weights.sum()
    cohort_idx = rng.choice(MONTHS, size=n_cust, p=weights)

    customers = []
    for i in range(n_cust):
        cid = 10_000 + i
        cm = months[cohort_idx[i]]
        day = int(rng.integers(0, 28))
        signup = cm + timedelta(days=day)
        country = _choice(rng, COUNTRIES, COUNTRY_W, 1)[0]
        channel = _choice(rng, CHANNELS, CHANNEL_W, 1)[0]
        handle = f"user{cid}"

        # Wart 1: inconsistent email casing and stray whitespace.
        email = f"{handle}@example.com"
        r = rng.random()
        if r < 0.08:
            email = email.upper()
        elif r < 0.13:
            email = f"  {email} "

        # Wart 2: internal test accounts never excluded by the source system.
        if rng.random() < 0.012:
            email = f"qa+{handle}@test.internal"

        # Wart 3: country missing for ~4% of rows.
        if rng.random() < 0.04:
            country = ""

        customers.append(
            {
                "customer_id": cid,
                "email": email,
                "signup_date": signup.isoformat(),
                "country": country,
                "acquisition_channel": channel,
            }
        )

    # ---- products ---------------------------------------------------------
    products = []
    pid = 500
    for cat, (lo, hi) in CATEGORIES.items():
        for n in range(12):
            price = float(rng.integers(lo, hi))
            price = round(price / 50) * 50
            products.append(
                {
                    "product_id": pid,
                    "product_name": f"{cat.title()} Item {n + 1:02d}",
                    "category": cat,
                    "unit_cost": round(price * float(rng.uniform(0.32, 0.55)), 2),
                    "list_price": price,
                }
            )
            pid += 1
    price_by_pid = {p["product_id"]: p["list_price"] for p in products}
    pids = np.array([p["product_id"] for p in products])
    pids_by_cat = {
        cat: np.array([p["product_id"] for p in products if p["category"] == cat])
        for cat in CATEGORIES
    }

    # Real baskets are not random. These pairs co-occur more often than chance,
    # which is what gives the market-basket query (Q10) something true to find.
    # A uniformly random basket produces lift ~= 1.0 everywhere and a query that
    # technically runs but discovers nothing.
    AFFINITY = {
        "skincare": ("haircare", 0.42),
        "makeup": ("tools", 0.35),
        "fragrance": ("bundles", 0.28),
        "haircare": ("skincare", 0.30),
    }
    CAT_NAMES = list(CATEGORIES)
    CAT_W = np.array([0.24, 0.18, 0.14, 0.21, 0.13, 0.10])
    CAT_W = CAT_W / CAT_W.sum()

    # November and December carry a holiday uplift. Without it, the revenue
    # trend query returns a straight line and the seasonality caveat in the
    # cohort analysis has nothing to point at.
    SEASON = {11: 1.55, 12: 1.70, 1: 0.82, 9: 1.12}

    # ---- orders and items -------------------------------------------------
    # Each customer gets two latent traits and then lives month by month:
    #
    #   lam    orders per active month
    #   retain probability of still being active next month
    #
    # Lifetimes are therefore geometric, which is what produces a realistic
    # convex retention curve. The earlier version drew a fixed order count per
    # customer and spread it over widening gaps; that gives everyone roughly the
    # same short lifespan, so by any later cutoff date essentially the whole base
    # looks dormant and a churn label becomes 99% one class -- unmodellable.
    #
    # Retention is a mixture, not a single distribution: a loyal minority with
    # very long lifetimes alongside a transient majority. Real subscription and
    # repeat-purchase bases look like this, and it is what makes the churn
    # problem in project 4 a genuine classification task rather than a formality.
    orders, items = [], []
    oid, oiid = 900_000, 1

    CHANNEL_LAMBDA = {
        "organic": 0.42, "paid_search": 0.36, "paid_social": 0.30,
        "email": 0.50, "referral": 0.52, "direct": 0.40,
    }
    CHANNEL_RETAIN = {
        "organic": 0.85, "paid_search": 0.80, "paid_social": 0.72,
        "email": 0.88, "referral": 0.89, "direct": 0.84,
    }
    LOYAL_SHARE = 0.26

    for c in customers:
        signup = date.fromisoformat(c["signup_date"])
        channel = c["acquisition_channel"]

        # Lognormal spread on the rate: most customers near the channel mean,
        # a thin tail of heavy buyers. That tail is what Q6 (revenue
        # concentration) and the RFM "big spender" segment are made of.
        lam = CHANNEL_LAMBDA[channel] * float(rng.lognormal(0.0, 0.55))

        is_loyal = rng.random() < LOYAL_SHARE
        if is_loyal:
            retain = float(np.clip(rng.normal(0.955, 0.02), 0.90, 0.99))
        else:
            retain = float(np.clip(rng.normal(CHANNEL_RETAIN[channel] - 0.06, 0.07), 0.45, 0.92))

        cursor = date(signup.year, signup.month, 1)
        alive = True
        n_orders_made = 0

        while alive and cursor <= months[-1]:
            season = SEASON.get(cursor.month, 1.0)
            n_this_month = int(rng.poisson(lam * season))

            for _ in range(n_this_month):
                # Days available in this month, respecting the signup date in
                # the first month so nobody orders before they exist.
                first_month = (cursor.year, cursor.month) == (signup.year, signup.month)
                day_lo = signup.day if first_month else 1
                day_hi = 28
                if day_lo > day_hi:
                    continue
                day = int(rng.integers(day_lo, day_hi + 1))
                ots = date(cursor.year, cursor.month, day)
                if ots < signup or ots > months[-1] + timedelta(days=27):
                    continue
                hour = int(np.clip(rng.normal(19, 4), 0, 23))
                stamp = datetime(ots.year, ots.month, ots.day, hour, int(rng.integers(0, 60)))

                # Wart 4: ~2% of timestamps arrive in a different format.
                ts_str = stamp.isoformat(sep=" ")
                if rng.random() < 0.02:
                    ts_str = stamp.strftime("%d/%m/%Y %H:%M")

                status = _choice(rng, STATUS_RAW, STATUS_W, 1)[0]
                orders.append(
                    {
                        "order_id": oid,
                        "customer_id": c["customer_id"],
                        "order_ts": ts_str,
                        "status": status,
                        "channel": _choice(rng, CHANNELS, CHANNEL_W, 1)[0],
                        "discount_code": ("" if rng.random() < 0.72
                                          else f"SAVE{int(rng.integers(5, 26))}"),
                    }
                )

                # Pick a lead category, then roll for its complement. Baskets
                # built this way have real structure instead of uniform noise.
                lead = str(rng.choice(CAT_NAMES, p=CAT_W))
                basket_cats = [lead]
                comp = AFFINITY.get(lead)
                if comp and rng.random() < comp[1]:
                    basket_cats.append(comp[0])
                basket_cats += [
                    str(rng.choice(CAT_NAMES, p=CAT_W))
                    for _ in range(int(rng.poisson(0.55 * season)))
                ]

                for cat in basket_cats:
                    pid_pick = int(rng.choice(pids_by_cat[cat]))
                    qty = 1 + int(rng.poisson(0.45 * season))
                    unit = price_by_pid[pid_pick] * float(rng.uniform(0.82, 1.0))

                    # Wart 5: a data-entry slip multiplies price by 100.
                    if rng.random() < 0.0015:
                        unit *= 100

                    # Wart 6: returns encoded as negative quantity on the
                    # original row rather than as a separate credit line.
                    if rng.random() < 0.004:
                        qty = -qty

                    items.append(
                        {
                            "order_item_id": oiid,
                            "order_id": oid,
                            "product_id": pid_pick,
                            "quantity": qty,
                            "unit_price": round(unit, 2),
                        }
                    )
                    oiid += 1

                oid += 1
                n_orders_made += 1

            # Survive into the next month, or go dormant for good.
            if rng.random() > retain:
                alive = False
            cursor = cursor + timedelta(days=32)
            cursor = date(cursor.year, cursor.month, 1)

    # Wart 7: ~1.2% of item rows are exact duplicates from a retried ETL load.
    n_dup = int(len(items) * 0.012)
    for j in rng.choice(len(items), size=n_dup, replace=False):
        items.append(dict(items[int(j)]))

    # Wart 8: a handful of orders reference customers that are not in the
    # customer table (deleted for a GDPR request upstream).
    for _ in range(40):
        stamp = datetime(2025, int(rng.integers(1, 13)), int(rng.integers(1, 28)), 12, 0)
        orders.append(
            {
                "order_id": oid,
                "customer_id": 999_999_000 + int(rng.integers(0, 60)),
                "order_ts": stamp.isoformat(sep=" "),
                "status": "completed",
                "channel": "direct",
                "discount_code": "",
            }
        )
        items.append(
            {
                "order_item_id": oiid,
                "order_id": oid,
                "product_id": int(rng.choice(pids)),
                "quantity": 1,
                "unit_price": 7500.0,
            }
        )
        oid += 1
        oiid += 1

    # ---- sessions ---------------------------------------------------------
    # Sessions exist so the funnel and attribution queries have something to
    # chew on. Conversion rate varies by device and source on purpose.
    sessions = []
    sid = 1
    orders_by_cust_day = {(o["customer_id"], o["order_ts"][:10]) for o in orders}
    for c in customers:
        signup = date.fromisoformat(c["signup_date"])
        n_sess = 1 + int(rng.poisson(9.0))
        for _ in range(n_sess):
            d = signup + timedelta(days=int(rng.exponential(70)))
            if d > months[-1] + timedelta(days=27):
                continue
            device = _choice(rng, DEVICES, DEVICE_W, 1)[0]
            source = _choice(rng, CHANNELS, CHANNEL_W, 1)[0]
            p_conv = {"mobile": 0.021, "desktop": 0.037, "tablet": 0.026}[device]
            p_conv *= {"email": 1.9, "referral": 1.6, "organic": 1.2, "direct": 1.1,
                       "paid_search": 1.0, "paid_social": 0.6}[source]
            bought_today = (c["customer_id"], d.isoformat()) in orders_by_cust_day
            converted = 1 if bought_today else int(rng.random() < p_conv)
            sessions.append(
                {
                    "session_id": sid,
                    "customer_id": c["customer_id"],
                    "session_date": d.isoformat(),
                    "device": device,
                    "source": source,
                    "pages_viewed": 1 + int(rng.poisson(3.1)),
                    "converted": converted,
                }
            )
            sid += 1

    # ---- marketing spend --------------------------------------------------
    spend = []
    for m in months:
        for ch in ["paid_search", "paid_social", "email", "referral"]:
            base_spend = {"paid_search": 2_400_000, "paid_social": 1_900_000,
                          "email": 180_000, "referral": 420_000}[ch]
            growth = 1 + 0.03 * months.index(m)
            spend.append(
                {
                    "spend_month": m.isoformat(),
                    "channel": ch,
                    "spend_ngn": round(base_spend * growth * float(rng.uniform(0.85, 1.15)), 2),
                }
            )

    return {
        "customers": customers,
        "products": products,
        "orders": orders,
        "order_items": items,
        "sessions": sessions,
        "marketing_spend": spend,
    }


def write(tables: dict, out: Path, sample_dir: Path | None, sample_rows: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    if sample_dir:
        sample_dir.mkdir(parents=True, exist_ok=True)

    for name, rows in tables.items():
        if not rows:
            continue
        cols = list(rows[0].keys())
        path = out / f"{name}.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        print(f"  {path}  {len(rows):,} rows")

        if sample_dir:
            with (sample_dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=cols)
                w.writeheader()
                w.writerows(rows[:sample_rows])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/raw", type=Path)
    ap.add_argument("--sample-out", default="data/sample", type=Path)
    ap.add_argument("--sample-rows", default=200, type=int)
    ap.add_argument("--seed", default=42, type=int)
    args = ap.parse_args()

    print(f"Generating warehouse (seed={args.seed})")
    tables = build(args.seed)
    write(tables, args.out, args.sample_out, args.sample_rows)
    print("Done. Load it with: python src/load_duckdb.py")


if __name__ == "__main__":
    main()
