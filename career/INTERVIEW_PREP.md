# Interview preparation

The portfolio gets the interview. This gets the offer. Rehearse out loud — the
gap between "I know this" and "I can say this in 90 seconds under pressure" is
the whole game.

---

## 1. The two-minute walkthrough, per project

Interviewers ask "talk me through a project". The failure mode is narrating the
pipeline from top to bottom. **Lead with the decision, not the method.**

The structure, every time: **Question → Finding → Decision → One hard thing.**

### Project 1 — SQL warehouse

> "A beauty e-commerce business was growing fast and wanted to know whether the
> growth was durable and where to put the retention budget. Revenue had doubled
> year on year, and the good news was that it was repeat-driven — the repeat
> share went from 9% to 70%. But the cohort curve was weak: only 12% of a
> signup cohort was still ordering at six months. Reconciling those two was the
> actual insight — a small loyal core was carrying a growing share of the
> business. I sized that core with an RFM segmentation and found 930 customers,
> about 18% of all-time revenue, who had been silent for a year. The
> recommendation was to move paid social budget into winback on that group.
>
> The hard part was a reproducibility bug I shipped. My segment sizes moved
> between runs — 1,006, then 1,003, then 1,029. `NTILE` buckets by row
> position, and my `ORDER BY` wasn't a total order, so ties got placed
> arbitrarily under parallel execution. I only caught it because my dashboard
> disagreed with my own README. Adding the primary key as a tiebreaker fixed
> it, and there's a test now that runs the query twice and asserts the results
> match."

### Project 2 — Python API analysis

> "I wanted a project on data I'd collected myself, so I built a client for the
> Wikimedia pageviews API and asked whether interest in professional topics
> drops at the weekend. It does — professional topics lose about a third of
> weekday traffic, leisure topics gain, and the ordering across articles lines
> up with the story.
>
> But the finding I'd actually bring to a team is methodological. The obvious
> test is a t-test on weekday days versus weekend days, and it gives an absurd
> p-value — because daily pageviews are autocorrelated at about 0.5, so those
> aren't independent observations. It's pseudo-replication. I switched to a
> paired weekly design: for each week, the ratio of weekend to weekday mean,
> tested on the log scale. The naive version overstated its confidence by about
> 15 orders of magnitude. Here the effect was so big both methods agreed — but
> on a 2% effect the naive test would have manufactured a finding."

### Project 3 — Dashboard

> "I built a retention dashboard for one person — the retention lead — and one
> decision: where next month's budget goes. I wrote the spec before building,
> and the part I'd point at is the list of things I deliberately left out:
> daily revenue, product breakdowns, forecasts, a total-customers counter. The
> test each panel had to pass was 'can the reader change what they do next month
> because of this?'
>
> Two details I care about: the current month is excluded in SQL, not in the
> chart code, because it's always partial and always looks like a collapse; and
> censored cohort cells are drawn as nothing rather than zero, because zero
> reads as total churn. Both of those are ways a dashboard lies to people who
> trust it."

### Project 4 — Capstone

> "I built a churn model and then designed the experiment to test what to do
> about it. The model is fine — 0.745 AUC validated out of time rather than on
> a random split, which matters because a churn snapshot isn't independent
> draws.
>
> The useful output was the power analysis, because it killed my own first
> design. I was going to target the 930 at-risk customers, send to 70%, hold
> back 30%. I ran the sample size calculation before writing the brief: to
> detect a reactivation lift from 6% to 9% I needed 1,209 per arm, and a 30%
> holdback of 930 is 279. That design could only have detected a seven-point
> lift. If the campaign had worked exactly as hoped, it would have come back
> p = 0.12 and we'd have concluded winback doesn't work.
>
> The fix was to widen the target to the full model-scored active base and
> split 50/50 instead of 70/30 — power is driven by the smaller arm, so an
> uneven split wastes population. That gets 1,377 per arm, and the same
> underlying effect now reads p = 0.003."

**Practise the last one most.** It is the strongest story you have: it shows
you running a check that cost you your own plan, and acting on the result.

---

## 2. Questions you will be asked about this work

| Question | The short answer |
|---|---|
| "Why synthetic data?" | Every project runs on a clean clone with no credentials, and the faults are known so cleaning decisions can be checked against ground truth. The cost is that no business finding describes a real company, and I say so at the top of each project. Project 2 ships a real API client. |
| "Isn't synthetic data easier?" | Harder, actually — I had to plant eight realistic faults and rebuild the generator twice. First version made 99% of customers look churned, which is unmodellable; I had to give customers geometric lifetimes to get a real classification problem. |
| "What would you do differently?" | Get a source of truth to reconcile against. I can prove internal consistency but not correctness. In a real job the first thing I'd ask for is finance's revenue number for one month, to check whether my "recognised revenue" definition matches theirs. It usually doesn't. |
| "Walk me through a bug you found." | The NTILE one. Lead with how you *noticed* — two views of the same query disagreeing. |
| "Your model's lift is only 1.5x." | At a 57% base rate the ceiling is 1/0.574 = 1.74x, so that's 86% of the best any model could do. The 5–10x figures in case studies come from problems with 2–5% churn. Comparing lift across base rates is meaningless. |
| "Why logistic regression and not XGBoost?" | I tried gradient boosting; it scored worse out of time (0.729 vs 0.745) and was less well calibrated. With 23 features and 2,088 training rows there's nothing for it to find that the linear model misses, and it costs interpretability. |
| "How do you know your numbers are right?" | Two independent implementations — hand-written SQL and dbt — and a test that asserts they agree to the naira. Plus the hand-rolled statistics are validated against statsmodels. |

---

## 3. Technical drills

Weekly, until they are automatic.

**SQL — write these from a blank page, no reference:**
- [ ] Running total and a 3-period moving average
- [ ] Nth highest value per group (`ROW_NUMBER` vs `RANK` vs `DENSE_RANK` — know the difference cold)
- [ ] Monthly cohort retention from a transactions table
- [ ] Gaps and islands: consecutive-day streaks per user
- [ ] Self-join for pairs (market basket), and why you need `a.x < b.x`
- [ ] Deduplicate keeping the latest row per key
- [ ] Pivot without `PIVOT`, using `FILTER` or `CASE`
- [ ] `LEFT JOIN` + `IS NULL` for anti-joins, and when `NOT IN` bites you with NULLs

**Know why, not just how:**
- When does a `JOIN` fan out, and how do you notice?
- `WHERE` vs `HAVING` vs `QUALIFY`
- Why `COUNT(DISTINCT x)` is expensive
- What a window frame default is (`RANGE UNBOUNDED PRECEDING`) and when it bites

**Statistics — be ready to explain in plain words:**
- [ ] What a p-value is **not** (it is not the probability the hypothesis is true)
- [ ] Why a confidence interval is the more useful output
- [ ] Power, and what an underpowered null result does and does not tell you
- [ ] Why you don't peek at a running A/B test
- [ ] Simpson's paradox, with an example
- [ ] When to use median over mean (and name a real case)

**Case / product sense:**
- [ ] "Daily active users dropped 8% yesterday. What do you do?"
      (Check the pipeline before the business. Then: is it one segment, one
      platform, one geography? Compare to the same weekday.)
- [ ] "How would you measure whether feature X is successful?"
- [ ] "We want to give a discount to customers likely to churn. Any concerns?"
      (You will reward people who were going to stay, and train customers to
      lapse in order to get discounts. Hold back a control.)

---

## 4. The behavioural ones

Have a concrete story ready for each — from this portfolio if you have nothing
better yet:

- **A time you found an error in your own work** → the NTILE bug, or the
  refund filter.
- **A time you disagreed with a stakeholder** → the underpowered test. "I was
  asked for a campaign; I came back and said the campaign as scoped couldn't be
  measured, and here are three designs that can."
- **A time you had to explain something technical to a non-technical person** →
  the decision memo. Point at how the power problem is explained without the
  word "power" doing any work.
- **A time you were wrong** → the docstring that claimed the sample-size
  shortcut was anti-conservative when it is conservative.

---

## 5. Questions to ask them

Good questions signal seniority more than good answers do.

- "Who else writes SQL here, and where does the business logic live — in the
  warehouse, in the BI tool, or in people's heads?"
- "When two dashboards disagree about revenue, what happens?"
- "What's the last analysis that actually changed a decision?"
- "How do you decide what gets tested versus shipped on judgement?"
- "What would make you say I'd had a great first 90 days?"

---

## 6. The week before

- [ ] Re-read your own READMEs. You will be asked about a number and must not
      hesitate.
- [ ] Run `make all` and confirm it still works from a clean clone.
- [ ] Rehearse the four walkthroughs out loud, timed, to 2 minutes each.
- [ ] Have the repo open in a tab, and the decision memo in another.
- [ ] Write down the three numbers you most want to land. For this portfolio:
      **124% YoY growth, 12% six-month retention, and the 7-point MDE that
      killed the first design.**
