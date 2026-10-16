# Data quality findings

Run `[command]` to reproduce every number below.

This report exists because the first question anyone asks about a new number is
"do you trust it?", and the only good answer is a count.

| # | Fault | Scale | If ignored | Decision |
|---|---|---|---|---|
| 1 | [what is wrong] | [rows and %] | [the specific wrong answer it causes] | [what you did] |

**The "if ignored" column is the one that matters.** "4% of countries are null"
is a fact. "4% of customers vanish from every country breakdown" is a finding.

---

## The decisions worth arguing about

**[Fault N] — [the principle, e.g. "flag, don't fix"].** [Why you chose this.
What the tempting alternative was. What it would have cost.]

[If you set a threshold, say what it is, and show the evidence that justifies
it — the distribution, the gap you placed it in. A threshold with no evidence
behind it is a guess.]

---

## A fault I introduced and then fixed

[If you found a bug in your own work, put it here. How you noticed matters as
much as the fix. This section does more for your credibility than a clean
report would.]

---

## What this audit does not cover

- **No source of truth to reconcile against.** I can prove internal consistency
  but not correctness. [What you would ask for in a real job.]
- **[Freshness / completeness / an unverifiable dimension.]**
- **[Anything you checked for and could not test.]**
