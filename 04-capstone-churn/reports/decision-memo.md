# Decision memo: winback test for the at-risk customer base

**To:** Head of Growth
**From:** Data
**Date:** 2026-10-15
**Decision requested:** approve a 90-day randomised winback test on 2,754
customers, with a 50% holdback.

---

## The ask in one page

We have 930 customers who each ordered about five times, spent an average of
₦175,101, and have now been silent for 366 days. They are 17.8% of all-time
revenue. Nobody is contacting them.

I built a churn model to find them earlier and a test design to find out whether
contacting them works. **Three things for you to decide on, and one number that
changed my own recommendation.**

1. **Approve the test, not the campaign.** A full-base winback send would cost
   about ₦33,000 and we would learn nothing from it, because we would have
   nothing to compare it against. The same spend with half the base held back
   tells us whether it worked.
2. **The test must run on 2,754 customers, not the 930.** This is the number
   that changed my mind — see below.
3. **Expect a decision in 90 days,** not sooner. Reading the result early is how
   a null result becomes a false positive.

---

## The number that changed the recommendation

My first design was the obvious one: take the 930 at-risk customers, send to
70%, hold back 30%. I ran the power calculation before writing the brief.

To detect a reactivation rate moving from 6% to 9% at 80% power, we need
**1,209 customers per arm**. Here is what each option actually gives us:

| Design | Treatment | Control | Smallest lift it can detect | Powered? |
|---|---|---|---|---|
| At-risk segment, 30% holdback | 651 | 279 | 6.93% | **No** |
| At-risk segment, 50% holdback | 465 | 465 | 5.14% | **No** |
| Model-scored active base, 30% holdback | 1,928 | 826 | 3.71% | **No** |
| **Model-scored active base, 50% holdback** | **1,377** | **1,377** | **2.79%** | **Yes** |

The obvious design could only have detected a lift of **7 percentage points** —
more than doubling the reactivation rate. Anything smaller and realistic would
have come back "not significant", and we would have concluded winback does not
work when in fact we had simply not measured it.

To show how bad that is: if the campaign delivered exactly the 6%→9% lift we are
hoping for, the underpowered design returns **p = 0.12 and a confidence interval
of −0.5% to +6.7%** — a real, valuable effect reported as a non-result. The
recommended design returns **p = 0.003** on the same underlying effect.

Two changes fix it:

- **Widen the target from the hand-drawn RFM bucket to the model score**, which
  takes the eligible population from 930 to 2,754. The cost is precision: the
  wider group is less concentrated in high-value customers, so revenue per
  reactivation falls.
- **Split 50/50 rather than 70/30.** Power is driven by the *smaller* arm, so an
  uneven split wastes population. 30% of 2,754 is 826, below the 1,209 we need;
  50% is 1,377, above it.

---

## What the model does and does not do

A logistic regression on 23 features, trained on a snapshot from **2 April 2025**
and tested on a different snapshot from **29 September 2025** — out of time, not
a random split.

| Metric | Value |
|---|---|
| ROC AUC (out of time) | **0.745** |
| PR AUC | 0.772 |
| Brier score | 0.207 (baseline 0.257) |
| Top-decile lift | **1.50x** |
| Share of churners in the top 10% | 15.0% |

**On the 1.50x lift, which looks unimpressive.** Churn in this base runs at
57.4%. When the base rate is that high, a *perfect* model could only achieve
1/0.574 = **1.74x** on the top decile, because the top decile is already 57%
churners before the model does anything. So 1.50x is **86% of the theoretically
best possible result**, not a weak one. The 5x–10x lifts quoted in churn case
studies come from problems where churn is 2–5%; comparing lift across different
base rates is meaningless.

**The practical consequence, which argues against heavy targeting.** Because
churn is so widespread, targeting buys less than it usually does. Contacting the
riskiest 10% reaches only 15% of churners. For an email campaign at ₦12 a head
the economics do not justify narrow targeting — contact the whole active base.
The model's real value is **timing and triage**, not exclusion: it tells us who
to contact *first* and whose silence is abnormal for them specifically.

**What the model is not.** It is a ranking, not an explanation. Two of the
fitted coefficients have the wrong sign relative to the raw data: the model says
more lifetime orders *increase* churn risk, while the data plainly shows churn
falling from 74% among one-order customers to 33% among those with eight or more.
The cause is collinearity — `orders_total` correlates 0.92 with `active_months`
and 0.90 with `revenue_total`, so the fit distributes shared signal between them
arbitrarily. **No coefficient in this model should be quoted as a cause.** The
check that caught this runs automatically
(`reports/univariate_direction.csv`, `reports/collinearity.csv`).

---

## If the test works

Using the hypothesised 6%→9% lift on the recommended design:

| | Amount |
|---|---|
| Gross revenue, point estimate | ₦2,976,026 |
| 95% range | ₦1,010,743 to ₦4,941,309 |
| Campaign cost | ₦16,524 |
| **Net, point estimate** | **₦2,959,502** |
| Net at the lower bound of the interval | ₦994,219 |
| Breakeven lift | 0.02% |

The range is the honest number, not the point estimate. Breakeven is so low
(0.02% versus the 3% we are testing for) that the campaign is worth running even
if it works far less well than hoped — **which is itself an argument for
approving the test rather than agonising over the forecast.**

Assumptions, each a way this could be wrong:

1. A reactivated customer places exactly one order in the window.
2. Average order value holds at ₦36,293.
3. The lift persists rather than decaying as novelty wears off.
4. No cannibalisation of other channels or of future purchases.
5. The 6% baseline reactivation rate is an estimate, not a measurement. **It is
   the biggest single uncertainty here** and the test will measure it directly in
   the control arm, which is a second reason to keep the holdback.

---

## Why a randomised test rather than a before/after comparison

We could send to everyone and compare the 90 days after against the 90 days
before. We should not. November and December are 131% above trend in both years
of data, and January falls 69%. A before/after comparison over any window
spanning that boundary measures the calendar, not the campaign.

A randomised holdout removes seasonality by construction: both arms live through
the same months. Where randomisation is impossible — the channel attribution
question in project 1, where we cannot randomise who sees a paid social ad — the
right tool is a geo holdout with a difference-in-differences read. That is a
separate, more expensive study and I am not proposing it here.

---

## What I need

- Engineering: a randomisation assignment stored per customer **before** the
  first send, so the arms cannot drift.
- Marketing: one creative, sent once, no follow-ups to the treatment arm, and
  **no sends at all to the control arm for 90 days**. The control arm is the
  whole experiment; contaminating it costs us the result.
- A written commitment not to read the result before day 90. Checking a running
  test repeatedly and stopping at the first significant reading inflates the
  false positive rate well past 5%. If an early read is genuinely required, say
  so now and I will design sequential boundaries for it instead.

---

## Reproduce this

```bash
make data warehouse
python 04-capstone-churn/src/churn_model.py --db warehouse.duckdb
PYTHONPATH=04-capstone-churn/src python 04-capstone-churn/src/design_winback_test.py --db warehouse.duckdb
```

Every number in this memo comes from `reports/model_metrics.json` and
`reports/experiment_design.json`, both regenerated by those two commands. The
statistics are implemented in `src/experiment.py` and validated against
statsmodels and scipy in `tests/test_experiment.py`.
