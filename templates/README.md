# Templates

The structures behind the four projects in this repository. They exist so a new
project starts from a shape that already works rather than a blank page.

| Template | Use it for |
|---|---|
| `PROJECT_README.md` | Any new analysis project. The order matters: finding, then method, then caveats. |
| `DECISION_MEMO.md` | The deliverable for a stakeholder. One page, written for someone who will not read the code. |
| `DATA_QUALITY_REPORT.md` | The audit you run *before* the analysis, not after someone questions it. |

## The three rules all of them encode

1. **Lead with the finding.** Methodology is evidence for the finding, not a
   narrative to walk through. Nobody reads a project top to bottom.
2. **State decisions with their costs.** "I dropped nulls" is a red flag.
   "I kept nulls as 'unknown' so that 4% of customers survive every GROUP BY,
   at the cost of a category that is not a real country" is an analyst.
3. **Name the limitation before someone finds it.** The competing explanation
   you cannot rule out, said first, reads as judgement. Said second, under
   questioning, reads as a gap.
