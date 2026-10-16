# Dashboard specification

Written before the dashboard was built. A dashboard without a named reader and a
named decision becomes a wall of charts that everyone glances at and nobody
uses, and the only way to avoid that is to decide who and what first.

---

## 1. Who reads it

**The retention lead.** One person, not "the business". They have a monthly
budget, a small email and SMS capability, and no analyst of their own.

They are not technical. They will not write SQL, change a filter they do not
understand, or read a caveat in a footnote. They look at this once a month,
for about four minutes, usually the day before a planning meeting.

## 2. The decision it supports

> **Where should next month's retention budget go?**

That is the whole scope. Every panel earns its place by informing that choice,
and anything that does not is left out no matter how interesting it is.

Three sub-questions, in the order the reader asks them:

1. *Are we in trouble?* → the four stat tiles
2. *Is the growth real or are we just buying it?* → new vs returning revenue
3. *Who exactly do I spend on?* → retention curve, segment table, channel
   efficiency

## 3. What was deliberately left out

| Left out | Why |
|---|---|
| Daily revenue | The decision is monthly. Daily data invites reacting to noise, and the reader has no lever that acts in a day. |
| Product and category breakdowns | Interesting, and merchandising's problem, not retention's. It belongs on a different dashboard with a different owner. |
| The market-basket lift analysis | Genuinely useful, genuinely not this decision. |
| Forecasts | The reader would treat a projection as a commitment. With two Novembers of history the uncertainty band would be wider than the signal. |
| A "total customers" counter | A number that only goes up. It cannot inform a decision, it just feels good. |
| Drill-down to individual customers | The action is a campaign to a segment. If they need a list, that is an export, not a dashboard. |

**The test for inclusion:** can the reader change what they do next month based
on this panel? If not, it is a report, not a dashboard.

## 4. Panels

| # | Panel | Form | Why this form |
|---|---|---|---|
| 1 | Four stat tiles | Hero numbers | A single number with a comparison is the right form for a headline. A chart of one value is not. |
| 2 | Revenue split, new vs returning | Stacked bars by month | Magnitude over time with a part-to-whole split. Stacked because the total matters as much as the split. |
| 3 | Average retention curve | Line with a min–max band | Change over an ordinal axis. The band carries the between-cohort spread, which a line alone hides. |
| 4 | Channel efficiency | Horizontal bars | Magnitude across named categories with long labels. Horizontal keeps the labels readable without rotating them. |
| 5 | Cohort retention | Heatmap + table toggle | Two dimensions plus a value. The table is the accessible equivalent, not an extra. |
| 6 | Segments | Table with an action column | Six rows and seven mixed-type columns. A table is the honest form; a chart would be decoration. |

## 5. Rules the build follows

**One axis per chart, always.** No dual-axis plots. Two measures on different
scales become two charts or an indexed common base.

**Colour follows the entity, never its rank.** Changing the period filter does
not repaint anything: new customers stay blue and returning stay orange whether
twelve months or twenty-four are on screen. A palette that re-sorts itself when
the data changes teaches readers to distrust the colours.

**The current month is never shown next to complete months.** It is always
partial and always looks like a collapse. `dash_kpi` and `dash_revenue_split`
both exclude it, in SQL, so no one can accidentally include it.

**Censored cohort cells are drawn as nothing, not as zero.** A cohort that has
not had six months yet has no month-6 cell. Rendering it as 0% would read as
total churn.

**Averages are computed over a fixed set.** The retention curve averages only
cohorts with a complete six months, so every point on the line comes from the
same cohorts. Averaging over whatever is available bends the tail upward for
purely compositional reasons.

**Every percentage arrives from SQL with its denominator already applied.**
Nothing in the page averages an average.

**Logic lives in SQL, not in the BI layer.** A calculated field inside a Tableau
workbook is invisible to code review, impossible to unit test, and lost when
someone rebuilds the workbook. Everything here is in
`sql/dashboard_mart.sql`.

## 6. Accessibility

- Colour is never the only channel: the heatmap has a full table view, the
  stacked bars have a legend and tooltips, and the segment table states its
  recommendation in words.
- The categorical palette was validated with a colour-vision-deficiency
  simulator rather than eyeballed. Worst adjacent pair ΔE 9.2 (light) and 9.4
  (dark), against a target of ≥ 8.
- Dark mode is a selected set of steps validated against the dark surface, not
  an automatic inversion. The sequential ramp is reversed in dark mode, because
  the near-zero end has to recede toward the surface in both themes.
- Hit targets for tooltips are the full column or row band, never the mark
  itself.
- Works at phone width with no horizontal scrolling.

## 7. Annotations

Three panels carry a written annotation, generated from the data rather than
typed in:

- the revenue chart states how the repeat share moved between the first and last
  month on screen;
- the retention curve names the steepest month-to-month fall and its size;
- the channel panel states that the CAC is blended rather than causal, because
  that is the caveat most likely to be forgotten by the person acting on it.

An annotation that is hard-coded goes stale the first time the data updates and
then quietly lies. These are computed at render time.

## 8. Refresh

`make dashboard` regenerates `docs/dashboard/data.js` from the warehouse. In a
real deployment this is a scheduled extract; the shape of the JSON is the shape
a BI extract would have, so swapping the static file for a live connection
changes nothing above it.
