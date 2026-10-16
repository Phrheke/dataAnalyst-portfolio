# Query optimisation: three rewrites, measured

Most portfolios claim an optimisation win and give you no way to check it. This
one ships the benchmark:

```bash
python 01-sql-retail-warehouse/sql/bench.py --db warehouse.duckdb --scale 1
python 01-sql-retail-warehouse/sql/bench.py --db warehouse.duckdb --scale 10
```

The script asserts both versions return identical results before it times
anything, because a fast query that returns different numbers is not an
optimisation, it is a bug.

## Results

DuckDB 1.5.6, median of 9 runs, warm cache.

**Scale 1x** — 25,272 orders, 48,412 items, 104,449 sessions:

| Case | Slow | Fast | Speedup |
|---|---|---|---|
| 1. correlated subquery → window function | 12.0 ms | 6.9 ms | **1.8x** |
| 2. self-join on duplicated rows → distinct pairs first | 15.4 ms | 11.5 ms | **1.3x** |
| 3. filter after join → filter before join | 6.3 ms | 6.4 ms | 1.0x |

**Scale 10x** — 252,720 orders, 484,120 items, 1,044,490 sessions:

| Case | Slow | Fast | Speedup |
|---|---|---|---|
| 1. correlated subquery → window function | 90.5 ms | 59.8 ms | **1.5x** |
| 2. self-join on duplicated rows → distinct pairs first | 63.6 ms | 63.6 ms | **1.0x** |
| 3. filter after join → filter before join | 16.0 ms | 17.3 ms | **0.9x** |

Two of the three rewrites stop paying at scale. That is the finding, and it is
the opposite of what a CV bullet would claim.

## What the numbers actually say

### Case 1: the win is real but much smaller than the folklore promises

Replacing a correlated subquery with a window function is the canonical SQL
optimisation, and on Postgres or MySQL this shape routinely goes from minutes to
seconds, because the engine executes the subquery once per outer row.

DuckDB gets 1.8x, not 100x. The plan says why:

```
slow: ORDER_BY -> HASH_GROUP_BY -> PROJECTION -> LEFT_DELIM_JOIN
      -> HASH_JOIN -> SEQ_SCAN -> COLUMN_DATA_SCAN -> DELIM_SCAN
fast: ORDER_BY -> PROJECTION -> HASH_GROUP_BY -> HASH_JOIN -> SEQ_SCAN
```

`LEFT_DELIM_JOIN` and `DELIM_SCAN` are DuckDB's **decorrelation** operators. The
optimiser has already rewritten my correlated subquery into a join against a
de-duplicated subplan. It did most of the work for me; the remaining 1.9x is the
cost of materialising that intermediate instead of streaming a window.

So the honest claim is not "I made it 100x faster". It is: *on a modern columnar
engine this rewrite is worth roughly 1.5–1.8x, and the reason the textbook
promises more is that the textbook assumes a planner that cannot decorrelate.*
On Postgres the same rewrite would be worth far more, which is exactly why
knowing your engine matters. This is the only one of the three cases that still
pays at 10x scale.

### Case 2: the fix is correctness first, speed second

The slow version joins `bench_items` to itself on `order_id`. An order with two
skincare lines and three haircare lines produces **six** joined rows for one
basket. To get the right answer it therefore needs `count(DISTINCT order_id)` —
and that distinct-aggregate over an inflated intermediate is where the time
goes.

Collapsing to distinct `(order_id, category)` pairs *before* the join makes the
join smaller and lets a plain `count(*)` be correct:

```
slow: PROJECTION -> ORDER_BY -> HASH_GROUP_BY -> HASH_JOIN -> SEQ_SCAN
fast: PROJECTION -> ORDER_BY -> HASH_GROUP_BY -> SEQ_SCAN -> HASH_JOIN -> CTE_SCAN
```

1.3x at 1x scale and **1.0x at 10x** — the win evaporates, because the
hash-aggregate that computes `count(DISTINCT)` parallelises about as well as the
pre-aggregation does once there is enough data to saturate the threads.

So the speed argument for this rewrite is weak. The correctness argument is not,
and it is the reason to keep it: anyone who writes this self-join without
thinking about row multiplication and reaches for plain `count(*)` gets a wrong
answer that looks entirely plausible. Market-basket lift is exactly the kind of
metric nobody sanity-checks, so the wrong number survives to the slide deck. The
fast version makes the correct aggregate the natural one to write.

### Case 3: the optimisation that does nothing, reported as doing nothing

Hand-pushing the `WHERE` clauses into CTEs before the join is advice you will
find in every "SQL tips" listicle. Here it is **1.0x at small scale and 0.9x at
10x scale** — that is, within noise, and slightly worse once the data is big
enough to measure properly.

The plans are identical:

```
slow: PROJECTION -> ORDER_BY -> HASH_GROUP_BY -> HASH_JOIN -> SEQ_SCAN
fast: PROJECTION -> ORDER_BY -> HASH_GROUP_BY -> HASH_JOIN -> SEQ_SCAN
```

Operator for operator the same plan. The optimiser pushed the predicates down into the
scans on its own, so my "optimisation" changed nothing except the amount of SQL
a human has to read. I am keeping this case in the benchmark precisely because
it failed: an engineer who reports only their wins is not measuring, they are
selling.

## The method

1. Establish the baseline and **assert the results match** before timing.
2. Read `EXPLAIN`, don't guess. Case 1's `DELIM_JOIN` and case 3's identical
   plans were both invisible from the SQL alone.
3. Measure at more than one data size. Case 2 looked like a 1.3x win at 1x and
   turned into exactly nothing at 10x; case 3 crossed from "no change" to "tiny
   loss". A single-size benchmark would have reported two wins that are not
   there.
4. Take the median of repeated warm runs, not a single cold one.
5. Report the cases where the rewrite did nothing. Two of these three did.
6. Separate the correctness argument from the speed argument. Case 2 is worth
   keeping for a reason that has nothing to do with its timing.

## Dialect notes

The queries use `date_diff` and `quantile_cont`, which are DuckDB and Postgres
spellings. On BigQuery those become `DATE_DIFF(a, b, MONTH)` and
`APPROX_QUANTILES`. On BigQuery the cost model is also completely different —
bytes scanned, not milliseconds — so case 3 would be judged on whether the
filters enable partition pruning, and there the manual rewrite can matter a
great deal.
