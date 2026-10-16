# Project 1 — Retail warehouse analysis in SQL

**Question:** a beauty e-commerce business is growing fast and wants to know
whether the growth is durable, and where to spend the next ₦10m of retention
budget.

**Answer in one paragraph.** Revenue grew 124% year on year (₦283m in 2024 to
₦634m in 2025) and the growth is durable in the sense that matters: the share of
monthly revenue from repeat customers rose from 9% to 70%, so the business is no
longer renting its revenue from ad platforms. The problem is the shape of the
base underneath that number. Only 12% of a signup cohort is still ordering six
months later, the top revenue decile has grown to 36% of all revenue, and 930
customers who averaged five orders each have now been silent for 366 days —
17.8% of all-time revenue sitting in a segment nobody is contacting. Channel
efficiency differs by 17x (email returns ₦23.91 per ₦1 spent, paid social
₦1.44). **Recommendation: move paid social budget into email and winback on
those 930 customers, and move the lifecycle email trigger to day 25, which is
the median gap before a second order.**

---

## The five findings

### 1. Revenue more than doubled, and November is half the story
Year-on-year net revenue grew 124%, from ₦283m to ₦634m across 25,272 orders
from 7,800 customers. But the seasonality is extreme and almost identical in
both years: November jumps +131% in 2024 and +131% in 2025, and January gives
back 69%.

Any month-on-month target set in December will be missed in January for reasons
that have nothing to do with how the team performed. The trailing 3-month
average in the query exists so that nobody reads a single month as a trend.

→ `sql/02_analysis.sql`, Q1. `LAG` plus a 3-month trailing average window frame.

### 2. Growth is repeat-driven, which is the healthy kind
The share of monthly revenue from customers who were not new that month climbed
from 9% in February 2024 to a stable 59–70% through 2025, ending at 69.6%.

This is the single most diagnostic chart in e-commerce. A business whose growth
is all first-time buyers collapses the moment ad costs rise; this one would not.

→ Q2. `MIN(order_month) OVER (PARTITION BY customer_id)` to classify each order
as the customer's first or a repeat.

### 3. But only 12% of a cohort survives six months
Averaged over the **18 cohorts that have a full six months of history** (the six
most recent are still censored and are excluded, which is why this is not an
average over all 24):

| Months since signup | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|
| Still ordering | 32.7% | 24.4% | 21.1% | 18.0% | 15.8% | 13.1% | **12.2%** |

The curve is a smooth convex decay with the steepest fall in the first two
months, and it is near-identical in all 18 cohorts — structural, not a bad
quarter. Reconciling findings 2 and 3 is the actual insight: **revenue growth is
repeat-driven while the cohort curve is weak, which means a small loyal core is
carrying an increasingly large share of the business.** Finding 4 sizes that core
and finding 5 says it is being under-funded relative to paid acquisition.

→ Q3. Cohort size measured **at signup**, not at month-0 activity. See the
caveat on month 0 below — it matters.

### 4. Nearly one naira in five comes from customers who have already gone quiet
RFM segmentation on all 7,800 buyers:

| Segment | Customers | Avg orders | Avg revenue | % of revenue | Days since last order |
|---|---|---|---|---|---|
| champion | 1,629 | 6.57 | ₦244,907 | **43.5%** | 23 |
| steady | 2,480 | 2.15 | ₦66,865 | 18.1% | 176 |
| **at risk — was loyal** | **930** | **4.98** | **₦175,101** | **17.8%** | **366** |
| big spender | 282 | 6.52 | ₦293,216 | 9.0% | 132 |
| lapsed | 1,548 | 1.10 | ₦38,941 | 6.6% | 418 |
| promising new | 931 | 1.14 | ₦50,050 | 5.1% | 27 |

The at-risk segment is the opportunity: these customers bought five times each
and spent more per head than the "steady" group, and they have been silent for
over a year. Recovering even a small fraction of them is cheaper than acquiring
their equivalent — which is exactly the claim project 4 designs a test for,
rather than asserting.

Note also the concentration risk: champions are 21% of buyers and 44% of
revenue.

→ Q5. `NTILE(5)` on recency, frequency and monetary, mapped to named segments,
because "RFM 544" is not something a marketing manager can act on.

### 5. Channel efficiency differs by 17x
Revenue per naira of spend, over each cohort's first 12 months:

| Channel | Customers | Blended CAC | 12-mo revenue/customer | Revenue per ₦1 spent |
|---|---|---|---|---|
| email | 1,430 | ₦4,115 | ₦98,390 | **₦23.91** |
| referral | 949 | ₦14,276 | ₦100,016 | ₦7.01 |
| paid_search | 2,422 | ₦31,961 | ₦60,729 | ₦1.90 |
| paid_social | 2,287 | ₦28,071 | ₦40,301 | **₦1.44** |
| organic | 3,110 | — | ₦78,420 | no spend recorded |
| direct | 1,662 | — | ₦75,036 | no spend recorded |

Paid social is not losing money, but it buys the weakest customers in the book:
₦40,301 of 12-month revenue against email's ₦98,390, at seven times the cost per
head.

→ Q8. **This is a blended CAC, not a causal one.** Spend is recorded per channel
per month with no customer-level attribution, so some of the organic and direct
revenue was almost certainly created by paid impressions. The honest reading is
"paid social is the worst of the four paid channels by a wide margin", not
"switching off paid social saves ₦28,071 per customer". Proving the causal
version needs a geo holdout; project 4 explains why that is the right design and
what it would cost.

---

## Supporting findings

- **Mobile is 68% of sessions and converts worst.** 3.91% on mobile against
  5.75% on desktop, with an overall rate of 4.44%. The worst cell is paid social
  on mobile: 2.70% across 13,469 sessions. The best is email on desktop: 9.06%.
  Paid social is the weakest source on every device, which is consistent with
  finding 5. (Q9)
- **Revenue concentration is rising.** The top decile of customers is 35.9% of
  revenue and the top three deciles are 68.0%. That makes the retention problem
  in finding 3 a concentration risk, not just a volume one: losing the top
  decile would cost more than a third of the business. (Q6)
- **The second order comes at about 25 days.** Median gap to the second order is
  25 days, and it stays remarkably flat at 24–26 days for the third through
  sixth orders. A winback email sent at day 60 is late by a factor of two. (Q7)
- **Haircare and skincare are genuinely complementary.** 53.9% of haircare
  orders also contain skincare, a lift of 1.37 over what independence predicts.
  Bundles and fragrance lift 1.40, makeup and tools 1.26. Every other pair sits
  at or below 0.65 — those only *look* related because both categories are
  popular, which is why the query reports lift rather than raw co-occurrence.
  (Q10)
- **Twelve-month LTV is about ₦82,827 per acquired customer**, averaged across
  cohorts. That is the number any CAC target has to be set against. (Q4)

---

## What I would do next

1. **Measure the winback properly.** The at-risk segment is the obvious target,
   but "email the lapsed list" is not a tested intervention. Hold back 30% as a
   control and measure incremental revenue, not open rates. Project 4 designs
   exactly this test.
2. **Get customer-level ad attribution.** Every channel number here is blended.
   Without click-level data or a geo holdout, the CAC table ranks channels but
   cannot price them.
3. **Investigate mobile checkout.** A 1.6-point conversion gap on 71% of traffic
   is worth more than any retention campaign if it is a fixable UX problem rather
   than a mix effect. The query cannot tell the difference; session recordings
   could.
4. **Rebuild the cohort view on first purchase, not signup.** See the caveat
   below. Both definitions are defensible and they answer different questions.

---

## Caveats and limitations

**Month 0 retention is only 32.7%, which looks broken but is not.** Cohorts
here are defined by **signup month**, not first purchase, and a customer who
signs up on the 28th has three days left in month 0 to place an order. Month 0
is therefore a partial window by construction, and it also includes the large
share of signups who never buy at all. If cohorts were defined by first purchase
instead, month 0 would be 100% by definition and the whole curve would shift up.

I kept signup-based cohorts because the business question is "do the people we
acquire become customers", which first-purchase cohorts cannot answer — they
silently exclude everyone who never bought, which is the majority. Both
definitions are defensible and they answer different questions; what is not
defensible is failing to say which one is on the axis.

**Revenue excludes cancelled, refunded and pending orders.** That single
assumption is declared once in `stg_orders.revenue_recognised` and never
re-litigated downstream. It removes 5,565 of 31,127 orders; a further 299 are
test-account orders and 40 are orphans, leaving 25,272 in `analysis_orders`.

**Returns are reported separately, not netted off silently.** The source system
encodes a return by flipping the original line's quantity negative instead of
writing a credit note, so `gross_revenue` and `return_value` are separate
measures and `net_revenue` is their difference. 21 customers have negative
lifetime revenue as a result, the worst at −₦45,916; those are real
refund-exceeds-purchase cases, and I checked them individually rather than
assuming.

**The RFM segment sizes were non-deterministic until I fixed them.** `NTILE`
assigns buckets by row position, so when its `ORDER BY` is not a total order the
engine may place tied rows in any sequence. DuckDB's parallel scan genuinely
does vary between runs: three consecutive runs of the original Q5 put
**1,006 / 1,003 / 1,029** customers in the "at risk" segment. Adding
`customer_id` as a tiebreaker to every `NTILE` ordering makes it stable, and
`tests/test_staging.py::test_ntile_segments_are_deterministic` runs the query
twice and asserts the results match. I found this because the dashboard's
segment table disagreed with this README — two views of the same query
disagreeing is exactly the symptom, and it is worth saying that I shipped the
bug before I caught it.

**This is synthetic data.** It is generated deterministically by
`src/generate_warehouse.py` with a fixed seed, so the numbers above are
reproducible by anyone who clones this repo, and it carries deliberately planted
data quality faults (documented in `data_quality/FINDINGS.md`). It is not real
company data and no finding here describes a real business. The point of the
project is the method; see `../README.md` for how to swap in a real dataset.

---

## Technique index

For anyone scanning for specific SQL:

| Technique | Where |
|---|---|
| CTEs, layered staging → marts | `sql/01_staging.sql` |
| `LAG`, trailing-average window frames | Q1 |
| `MIN() OVER (PARTITION BY ...)` | Q2 |
| Cohort retention, `date_diff`, pivot with `FILTER` | Q3 |
| Cumulative `SUM` over `UNBOUNDED PRECEDING` | Q4 |
| `NTILE(5)`, reversed ordering for recency | Q5 |
| Nested window aggregate `sum(sum(x)) OVER ()` | Q6 |
| `ROW_NUMBER` + `LAG` for inter-event gaps | Q7 |
| Multi-table join with spend reconciliation | Q8 |
| `FILTER` aggregates, window share-of-total, scalar subquery | Q9 |
| Self-join market basket, support and lift | Q10 |
| Deterministic de-duplication by `ROW_NUMBER` | `stg_order_items` |
| `TRY_CAST` / `TRY_STRPTIME` multi-format parsing | `stg_orders` |

---

## Run it

From the repository root:

```bash
make data          # generate the CSVs (deterministic, seed 42)
make warehouse     # load into DuckDB and build the views
make sql           # run the analysis queries and print results
```

Or by hand:

```bash
python src/generate_warehouse.py --out data/raw
python src/load_duckdb.py --db warehouse.duckdb --raw data/raw
duckdb warehouse.duckdb < 01-sql-retail-warehouse/sql/01_staging.sql
duckdb warehouse.duckdb < 01-sql-retail-warehouse/data_quality/profile.sql
duckdb warehouse.duckdb < 01-sql-retail-warehouse/sql/02_analysis.sql
```

### The same models, twice

`dbt/` rebuilds the staging and mart layer as a tested dbt project
(59 tests, all passing):

```bash
cd 01-sql-retail-warehouse/dbt && dbt build --profiles-dir .
```

`tests/test_parity.py` in the repository root then asserts that the dbt
warehouse and the hand-written SQL produce **identical** numbers — same order
count, same revenue to the naira, same retention curve, same outlier count. Two
independent implementations agreeing is the cheapest real check on either one,
and it runs in CI on every push.

The warehouse is DuckDB, which is a real columnar engine with full window
function support and runs from a single file with no server. The same SQL runs on
Postgres and BigQuery with only `date_diff` and `quantile_cont` needing dialect
changes — noted inline where it matters.

## Files

```
01-sql-retail-warehouse/
├── README.md                     this file
├── schema/ERD.md                 table relationships and grain
├── sql/01_staging.sql            cast, clean, de-duplicate, define marts
├── sql/02_analysis.sql           the ten business questions
├── sql/03_optimisation.md        a slow query, why it was slow, and the rewrite
├── data_quality/profile.sql      the audit that runs before any analysis
├── data_quality/FINDINGS.md      what the audit found, and what I did about it
└── dbt/                          the same models as a tested dbt project
```
