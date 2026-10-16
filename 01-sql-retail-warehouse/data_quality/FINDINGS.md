# Data quality findings

Run `duckdb warehouse.duckdb < data_quality/profile.sql` to reproduce every
number below.

This report exists because the first question anyone asks about a new number is
"do you trust it?", and the only good answer is a count. Eight faults, what each
one would have done to the analysis, and what I did about it.

| # | Fault | Scale | If ignored | Decision |
|---|---|---|---|---|
| 1 | Email case and whitespace inconsistent | ~13% of rows | No collisions *in this dataset*, but any join against a correctly-cased external list (an ESP export, a support tool) silently misses those rows | `lower(trim())` in staging |
| 2 | Internal QA accounts in production data | 140 customers, 299 orders | Inflates customer count and drags AOV | Flagged in staging, excluded in `analysis_orders` |
| 3 | `country` missing | 483 rows (4.03%) | 4% of customers vanish from every country breakdown | Kept as `NULL`, plus `country_filled = 'unknown'` so rows survive `GROUP BY` |
| 4 | `order_ts` in two formats | 622 rows (2.0%) | A plain `CAST` NULLs them — real revenue deleted, biased to whichever weeks the broken exporter ran | `coalesce(try_cast, try_strptime)` recovers all 622 |
| 5 | `unit_price` x100 typos | 72 item rows | One ₦4.2m line item distorts AOV, LTV and every mean | Flagged `is_price_outlier`, excluded from revenue measures, **not** overwritten |
| 6 | Returns encoded as negative quantity on the original line | 261 rows | "Revenue" silently nets off refunds without being asked to | Split into `gross_revenue` and `return_value`; `net_revenue` is their difference |
| 7 | Duplicate item rows from an ETL retry | 717 rows (1.18%) | Revenue overstated by ~1.2%, basket sizes inflated | De-duplicated by `ROW_NUMBER()` on the primary key |
| 8 | Orders referencing deleted customers | 40 orders, ₦300,000 | An `INNER JOIN` drops real revenue and nobody notices | `LEFT JOIN` + `is_orphan_order` flag; counted in revenue totals, excluded from customer-level analysis |

## The two decisions worth arguing about

**Fault 5 — flag, don't fix.** A line item priced at roughly 100x its product's
list price is a data-entry slip, not a sale. The tempting fix is to divide by 100. I did not, because
I cannot know that 100 is the right divisor for every case, and a silently
corrected value is a number nobody can audit later. Excluding 72 rows out of
60,585 and documenting it costs almost nothing; inventing 72 prices costs the
reader's ability to trust the other 60,513.

Threshold: `unit_price > list_price * 20`. That is a judgement call. The
profiling query prints the flagged rows with their price-to-list ratio so a
reviewer can disagree with the threshold on evidence — the real ratios cluster
at ~99-100x, with nothing legitimate above 3x, so 20x is comfortably in the gap.

**Fault 8 — keep the revenue, drop the customer.** These 40 orders are real
money that the business really collected; the customer record was deleted
upstream for a GDPR request. Excluding them from revenue understates the
business. Including them in per-customer averages creates 40 phantom customers.
So: in revenue totals, out of customer-level analysis. Both behaviours are
explicit in `analysis_orders`.

## A fault I introduced and then fixed

The first version of `stg_order_items` gated `gross_revenue` on the price
outlier check but not `return_value`. A refund on a mistyped line therefore
produced a customer with **negative six-figure lifetime revenue**. The RFM
segmentation put them in the bottom monetary quintile and they looked like an
ordinary low-value customer.

Both measures are now gated on the same check. The lesson generalises: *if you
exclude a bad value from one measure you have to exclude it from every measure
derived from the same column*, and the way to catch it is to look at the extremes
of your outputs, not just your inputs. 21 customers still have negative
lifetime revenue, the worst at −₦45,916; those are genuine
refund-exceeds-purchase cases, and I checked them individually rather than
assuming.

## What the audit does not cover

- **No source-of-truth to reconcile against.** I can prove internal consistency
  but not correctness. In a real job the first thing I would ask for is the
  finance team's revenue figure for one month, to check whether my
  `revenue_recognised` definition matches theirs. It very often does not.
- **No freshness or completeness SLA.** The timeliness check (section 7) shows
  every month has data, which rules out a wholly missing load but not a partial
  one.
- **Sessions are unverified.** There is no way to tell a bot from a human in this
  data, and bot traffic would deflate every conversion rate in Q9.
