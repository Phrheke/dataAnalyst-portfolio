# Roadmap

A plan for turning this repository into interviews, written for someone who can
already write joins and basic pandas.

The honest framing first: **no portfolio guarantees a job.** What a portfolio
does is remove the reasons to reject you. The hiring funnel is roughly
*applications → screen → interview → offer*, and a portfolio mainly helps at the
first two steps. Referrals, volume and interview practice carry the rest.

---

## Where this repository already is

Done, and done to a standard you can defend:

- [x] SQL project with window functions, cohort retention, RFM, market basket
- [x] A data quality audit with decisions and their costs
- [x] A measured query optimisation study that reports its own null results
- [x] The same models rebuilt in dbt with 59 passing tests
- [x] A Python project with a real API client and correct statistics
- [x] A live, interactive, accessible dashboard with a written spec
- [x] A capstone with out-of-time validation and a pre-registered experiment
- [x] A one-page decision memo for a non-technical reader
- [x] A test suite, pinned dependencies, a Makefile and CI
- [x] Three self-found bugs documented rather than hidden

## What is still missing

- [x] **Move it to its own repository** — done: github.com/Phrheke/dataAnalyst-portfolio
- [ ] **Turn on GitHub Pages** so the dashboard and landing page are live
- [ ] **Swap project 2's fixture for real API data** — one command, and it
      makes that project about real-world data rather than a simulation
- [ ] **A project in a domain you actually know.** This is the single highest-value
      addition left, and nobody can do it for you — see below.
- [ ] A GitHub profile README pointing at this (draft in `GITHUB_PROFILE_README.md`)
- [ ] A LinkedIn profile that matches (draft in `LINKEDIN.md`)
- [ ] A CV (draft in `RESUME.md`)

---

## Weeks 1–2: ship and sharpen

| | Task |
|---|---|
| [x] | Create `dataAnalyst-portfolio` on GitHub, move this directory there, push |
| [ ] | Settings → Pages → deploy from `main` / `/docs`. Check both links work. |
| [ ] | Run `python 02-python-pageviews/src/collect.py` and re-run the analysis. Update that README's numbers and delete the fixture warning box. |
| [ ] | Replace the placeholder User-Agent in `collect.py` with your real repo URL |
| [ ] | Pin the repository on your GitHub profile |
| [ ] | Read every README once as a stranger would. Cut anything that is not a finding, a decision, or a limitation. |

## Weeks 3–5: the domain project

**This is the work that distinguishes you from everyone else with a portfolio.**

The four projects here prove method. A fifth project in a domain you genuinely
know proves *judgement* — you will spot things in the data that a generic
analyst cannot, and you can answer "why does that matter?" without guessing.

Pick a domain where you have real knowledge or a real interest:

| Domain | Free data |
|---|---|
| Nigerian / African markets | Nigeria Bureau of Statistics, CBN statistics bulletin, World Bank, Afrobarometer |
| Health & life sciences | ClinicalTrials.gov, GEO, ChEMBL, WHO GHO |
| Football / sport | StatsBomb open data, Understat, FBref |
| Public spending | OpenSpending, national budget portals, IATI aid data |
| Education | UNESCO UIS, national exam board statistics |
| Your own industry | Whatever you have touched professionally |

Rules that worked for the projects here:

- [ ] Avoid Titanic, Iris, and the top-20 Kaggle datasets entirely
- [ ] Write the question before touching the data
- [ ] Do the data quality audit **first**, and publish what you find
- [ ] State the decision your analysis supports, and who would make it
- [ ] End with limitations and "what I'd do next"
- [ ] Use `templates/PROJECT_README.md` so the structure matches the others

## Weeks 4–10: applying, in parallel

Start applying in week 4. Do **not** wait for the domain project — it improves
while you apply.

| | Weekly cadence |
|---|---|
| [ ] | 8–12 applications, tailored (see below) |
| [ ] | 3–5 referral attempts — far higher conversion than cold applications |
| [ ] | 1 timed SQL practice session (`INTERVIEW_PREP.md` §3) |
| [ ] | 1 case question answered out loud |
| [ ] | Log everything in `APPLICATION_TRACKER.csv` |

**Tailoring, concretely.** Takes ten minutes per application:
1. Reorder the project cards in your CV so the most relevant is first.
2. Match the job ad's vocabulary — if it says "A/B testing", your capstone is
   an *experimentation* project, not a *churn* project.
3. One line in the cover note naming something specific about them.

**On referrals.** Find someone at the company who does the job you want.
Message: one line on who you are, one line on something specific they or the
company did, one link, one ask. Do not attach a CV. Do not write three
paragraphs.

## Weeks 8–10: converting

| | Task |
|---|---|
| [ ] | Rehearse the four walkthroughs to 2 minutes each, out loud, timed |
| [ ] | Two mock interviews with a human |
| [ ] | Prepare your five questions for them |
| [ ] | Re-run `make all` before every onsite so nothing is stale |

---

## What to do when it is slow

Normal rates are brutal; this is not a signal that the work is bad.

- **No responses to applications** → it is a volume and referral problem, not a
  portfolio problem. Double the applications, triple the referral attempts.
- **Screens but no interviews** → your CV and the first 30 seconds of your
  self-introduction. Rewrite the CV summary.
- **Interviews but no offers** → it is the live SQL or the case questions.
  Drill §3 of `INTERVIEW_PREP.md` and do more mocks.
- **"You're too junior"** → ask what specifically. Usually it means stakeholder
  experience, not technical skill. Volunteer to do analysis for a small
  business, a church, an NGO, a local league — anything with a real person who
  wants a real answer.

## One thing to keep doing after you are hired

Write up one analysis a quarter the way the decision memo is written. The habit
of leading with the decision, stating the assumptions and naming the
limitations is what separates an analyst people trust from one they check.
