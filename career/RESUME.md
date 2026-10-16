# CV / résumé draft

A working draft built from this portfolio. **Fill the bracketed parts** — I do
not know your education or work history, and inventing them would be worse than
leaving gaps.

## Rules this draft follows

1. **One page** until you have five years of experience.
2. **Every bullet is a result, not a duty.** "Built a dashboard" is a duty.
   "Built a retention dashboard that cut the monthly planning review from two
   hours to twenty minutes" is a result. If you cannot quantify it, say what
   decision it enabled.
3. **Mirror the job ad's vocabulary.** If the ad says "experimentation", your
   capstone is an experimentation project. Same work, their words.
4. **No skills bar charts.** Nobody believes "SQL ▓▓▓▓▓░ 83%".
5. **Plain formatting.** Applicant tracking systems mangle columns, tables,
   icons and text boxes. One column, standard headings, a real PDF.

---

```
PHRHEKE [SURNAME]
[City, Country] · ruizdrey1@gmail.com · [phone]
github.com/Phrheke/dataAnalyst-portfolio · [linkedin.com/in/...]


SUMMARY
Data analyst who turns messy transactional data into decisions stakeholders can
act on. Comfortable from raw ingestion through SQL modelling to the one-page memo
that goes to the decision-maker. [X years of experience in Y / Recent transition
from Z, with a portfolio of four end-to-end projects.]


SKILLS
SQL          Window functions, CTEs, cohort analysis, query optimisation,
             dimensional modelling (DuckDB, PostgreSQL, BigQuery)
Python       pandas, scipy, scikit-learn, statsmodels, matplotlib
Analytics    Cohort retention, RFM segmentation, churn modelling, A/B test
             design and analysis, power analysis
Engineering  dbt, Git, GitHub Actions, pytest, data quality testing
BI           Dashboard design and specification, stakeholder requirements
             [+ Power BI / Tableau / Looker Studio once you have used one]


EXPERIENCE

[Job Title] — [Company], [Location]                          [Mon YYYY – Present]
• [Result, with a number. What changed because of your work?]
• [A time you found something nobody had asked you to look for.]
• [Something that shows you work with people, not only data.]

[Earlier role — include non-analyst roles. Stakeholder management, operations
 and customer work are all relevant; frame them that way.]


SELECTED PROJECTS                      github.com/Phrheke/dataAnalyst-portfolio

Churn prediction and winback experiment design
• Built a churn model validated out of time (ROC AUC 0.745) rather than on a
  random split, and reported the optimism gap against in-snapshot validation.
• Ran a power analysis that invalidated the original campaign design: it could
  only have detected a 7-percentage-point lift, so a real effect would have been
  reported as "no effect". Redesigned the target and the split to make the test
  measurable.
• Delivered a one-page decision memo with the revenue range, the breakeven
  threshold, and every assumption stated.

SQL warehouse analysis and dbt models
• Modelled a 31k-order retail warehouse through staging and mart layers; answered
  ten business questions using window functions, cohort retention, RFM
  segmentation and market-basket lift.
• Found that 12% of a signup cohort survives six months while 18% of all-time
  revenue sat in a segment silent for a year; recommended reallocating paid
  social budget to winback.
• Rebuilt the same models in dbt with 59 passing tests, and wrote a parity test
  asserting both implementations agree to the naira.
• Audited data quality before analysing: recovered 622 orders whose timestamps a
  naive cast would have silently dropped, and de-duplicated 717 ETL-retry rows.

Retention dashboard (live)
• Designed for one stakeholder and one recurring decision, with a written
  specification listing what was deliberately excluded and why.
• Built the mart so all logic lives in SQL rather than in the BI layer, and
  validated the colour palette against colour-vision deficiency simulation.

Python API analysis
• Built an API client with retry, backoff, caching and provenance capture.
• Identified pseudo-replication in the obvious analysis: daily observations were
  autocorrelated at 0.5, so a day-level test overstated its confidence by ~15
  orders of magnitude. Switched to a paired weekly design and confirmed the
  result across five sensitivity variants.


EDUCATION
[Degree, Institution, Year]
[Relevant certifications]
```

---

## Tailoring checklist, per application

- [ ] Reorder the four projects so the most relevant is first
- [ ] Rewrite the summary line using the ad's own words
- [ ] Drop any bullet the ad gives no signal about — one page, always
- [ ] If the ad names a BI tool you have not used, say so honestly in the cover
      note and point at the dashboard spec as evidence you understand the craft
- [ ] Export to PDF, named `Phrheke-[Surname]-Data-Analyst.pdf`
- [ ] Open the PDF and read it on a phone before sending

## Cover note template

Three short paragraphs. Nobody reads four.

> Hi [name],
>
> I'm applying for [role]. [One specific sentence about them — a product
> decision, a post, something in the ad that is not boilerplate.]
>
> The closest thing I have to the work you've described is [project], where
> [one-sentence result]. The write-up is here: [direct link to that project, not
> the repo root].
>
> Happy to walk through any of it.
>
> Phrheke
