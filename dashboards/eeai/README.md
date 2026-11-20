# EEAI: the Economic Effects of AI dashboard

EEAI asks the standing model panel FRI's "Economic Effects of AI" expert survey
and draws the answers. v0, 2026-11-11.

## What is in this directory

The whole dashboard. Outside it EEAI uses only the harness
(`packages/forecaster`: the panel, the Baseline condition, the agent loop,
search) and AIRO's Epoch snapshots (`dashboards/airo/data/`).

```
eeai/
  README.md            this file
  make_questions.py    the survey documents -> data/questions.json, data/history.csv
  survey.py            what the question set asks for
  instrument.py        the prompt, the answer tools, the cleaning
  run.py               ask the panel -> results/runs/<stamp>.jsonl
  build.py             the run files -> the page
  export.py            the download (eeai-data.zip)
  synthetic.py         made-up answers, for the page and the tests
  model/               the economy model (v0): definition, instrument, run, simulation, its page's data
  data/                questions.json, history.csv (tracked); source/ (FRI's documents, not tracked);
                       model/ (components.json, baselines.csv; model/source/ not tracked)
  web/                 the page's source: chunks, manifest, img/; fonts/ (licensed, not tracked)
  web-model/           the economy model's page (model.html)
  tests/               pytest eeai/tests
  results/             the run files (not tracked)
  site/                the built site (not tracked)
```

Run every command from this directory (`dashboards/eeai`).

## What is asked

The survey's questions, in one call per model (`python3 -m eeai prompt` prints
it), each also asked at nearer dates that FRI added (instrument
`eeai-survey-v3`; v3 adds the resolution rules and pins the baseline, v2 added the near dates, and v1 was the survey's own dates only, and its rows continue):

- **AI progress.** The probability of each of the survey's three scenarios for
  AI capability at the end of 2030 (slow, moderate, rapid), the relative
  importance of the five capability indicators, and two milestone probabilities
  (a household robot; reliability).
- **Economic outcomes.** 15 questions about the US economy at the beginning of
  2027, 2028 and 2029 (added) and of 2030 and 2050 (the survey's)
  (GDP, labor and total factor productivity, participation, unemployment, youth
  unemployment, three job-category shares, wealth inequality, labor share,
  median household income, life satisfaction, AI-assisted work hours, AI
  electricity use). Each is asked unconditionally and under each scenario; the
  five the survey tags "uncertainty" also ask the 10th and 90th percentiles,
  unconditionally and under rapid. 396 numbers (156 of them the survey's own),
  and a rationale per question. A near date is the survey's 2030 wording with
  its years moved back, so a five-year growth window stays five years and
  every forecast is a later point on the charted series. Once a date has
  passed, the panel is no longer asked about it and its last forecast stands.

Wording, definitions and resolution sources are the survey's, verbatim
(`eeai/make_questions.py` -> `eeai/data/questions.json`). Where a human
respondent saw a chart, the model gets the series (`eeai/data/history.csv`).

Not asked, by decision: Part 2 (short-term forecasts) and Part 4 (policies),
whose dates have passed or are weeks away; the items that measure the respondent
(the knowledge quiz, the worldview items, policy support, the cognitive tasks);
and the occupation ranking, whose occupation subsets are in a sheet outside the
survey.

## How it is asked

The Baseline condition on the shared panel, both from `packages/forecaster`:

- `fri_forecaster.panel`: the four highest-ECI models we can run, one seat per
  model family, from the newest Epoch snapshot under the repository's `data/`
  (`EEAI_ECI_DIR` names another directory).
- `fri_forecaster.baseline`: no system prompt, web search and page reading
  offered (Tavily) and never required, reasoning at the top level, no debrief.
  This is AIRO's published `none` condition.
- The models cannot search or read FRI's own pages (`forecastingresearch.org`
  and its subdomains, and FRI's Substack): the human panel's answers to this
  survey are published there, and the first smoke call read them. The list is
  `eeai.config.BLOCKED_URLS`; each call records it. A snippet on someone
  else's page can still quote FRI.

```bash
python3 -m eeai prompt                        # the prompt, the tools, the panel; calls nothing
python3 -m eeai run --smoke                   # PAID: the top model only
python3 -m eeai run                           # PAID: the panel -> eeai/results/runs/<stamp>.jsonl
python3 -m eeai run --resume RUN_ID           # PAID: the models that run does not have yet
python3 -m eeai build                         # the run files -> eeai/site/
python3 -m eeai run --synthetic --out DIR     # made-up answers, to look at the page
python3 -m eeai build --runs DIR --site DIR
```

A run refuses to start without `TAVILY_API_KEY`. Keys are read as the harness
reads them (`fri_forecaster/keys.py`).

## The page

`python3 -m eeai build` writes `eeai/site/`: `index.html` (assembled from
`eeai/web/` by the dashboard kit, `packages/dashboard`), `eeai-data.zip`, and the logo and fonts the
page links to. The folder is self-contained; any static web server can serve
it. The panel's number is the median across models of each value. The page
draws what is asked: points at each date, joined to the latest data by
straight lines. A recorded outcome appears alongside the forecast. The table
shows the signed error for unconditional forecasts and for the realized AI
scenario once FRI records its end-of-2030 decision.

The headline charts for real GDP growth, labor force participation, and the wealth share of the top 10% share a Current/History toggle. The remaining indicators have their own toggle. Current
shows forecasts by target year. History tracks one target across forecast
runs and shows the outcome once available. The horizon and AI progress
controls apply across both chart areas. A fresh visit opens on the long-term view with 2050 selected and forecasts conditional on AI progress. Near-term covers the five calendar
years after the latest run. Long-term shows the original 2030 and 2050
targets. History includes a year selector within the chosen window.
The page address preserves these choices (for example,
`#split=1&term=long&horizon=2030&history=hero`).

Hover a target year to compare the available model and human forecasts on one
axis. Each tooltip row gives the forecast date. Human forecasts use the
October 2025–February 2026 fieldwork period reported in the
[study methods](https://forecastingresearch.org/research/economic-effects-of-ai).
In the conditional view, hovering a scenario line reveals its elicited 80%
interval where available. Open any forecast card for all forecast tables, the question definition and rationales.

Motion is small and optional: the modal fades in and out, the control just
used presses in, and the forecasts (not the record or the axes) fade in when a
control redraws a chart. A reader who asks for reduced motion gets none.

One control switches every chart between the unconditional forecast and the
forecasts conditional on AI progress (the three scenarios, with no
unconditional line). `eeai-data.zip` (`eeai/export.py`) holds the forecasts, rationales and AI progress answers as CSV,
the questions, the history and the run files. The page's "Download data"
buttons serve it.

## The economy model (v0)

A second instrument, beside the survey, that will eventually replace it. The
design is FRI's note "Initial economy model for the dashboard" (13 and 18
November 2026). The panel forecasts the components of an accounting model of
the US economy, and every top-line outcome is computed from them:

- **Components.** 22 industries and 22 occupation groups. By industry: real
  value added, its price, labor productivity, hours per worker, capital input,
  the labor share. The occupation mix (484 cells). By occupation: unemployment,
  median earnings, and four automation components. Population, the
  no-occupation unemployed, the earnings deciles, the ECI and the PCE price
  index. Five direct forecasts as cross-checks. That is 760 components, asked
  for 3 scenarios and 8 years (2026 to 2030, 2035, 2040, 2050) as five
  quantiles each, plus 711 baselines for 2025: 18,951 quantile sets per model,
  and the scenario probabilities.
- **Definition.** `eeai/data/model/components.json` is written by hand and
  compact (one template per kind of component); `eeai/model/spec.py` expands
  it. The scenarios are copied from the survey, verbatim.
- **One call per model.** The agent delivers in pieces with submit_cells; pi
  compacts the conversation as it fills, and each piece is kept on disk, so the
  answer is not limited by the context. The call gets 500 turns and 12 hours
  (`config.MODEL_MAX_TURNS`, `MODEL_TIMEOUT`); everything else is the Baseline
  condition. A retry asks only for the missing components. `--split scenario`
  or `--split block` asks in a few calls instead.
- **Simulation.** `eeai/model/simulate.py`: each quantile set is fitted with a
  five-term metalog (Keelin 2016) on a log or log-odds scale, falling back to
  straight lines in normal scores where the metalog is not increasing; 10,000
  independent worlds per scenario and model; the identities
  (`eeai/model/identities.py`); the unconditional forecast mixes a model's
  scenarios by its probabilities; the ensemble mixes the models with equal
  weight. Growth is the annual rate: year on year to 2030, then the average
  annual rate since the previous date shown.
- **The page.** `model.html` beside the survey's `index.html`, linked from both
  headers, built from `eeai/web-model/`, with its own download
  (`eeai-model-data.zip`). The survey page's data is unchanged.

```bash
python3 -m eeai model prompt                           # each call's size and token estimate (--show: the prompt)
python3 -m eeai model baselines --template             # data/model/source/published_2025.csv, to fill in
python3 -m eeai model baselines                        # CPS extract + published figures -> data/model/baselines.csv
python3 -m eeai model run --synthetic --out DIR        # made-up answers
python3 -m eeai model run --smoke                      # PAID: the top model only
python3 -m eeai model simulate RUN_FILE                # -> eeai/results/model/sims/ (needs: pip install -e '.[model]')
python3 -m eeai build                                  # both pages
```

**The 2025 record, by hand.** Download an IPUMS CPS extract (cps.ipums.org)
of the twelve 2025 basic monthly samples, as CSV, with YEAR, MONTH, WTFINL,
AGE, EMPSTAT, CLASSWKR, IND, OCC and AHRSWORKT, to
`eeai/data/model/source/cps_2025.csv` (not tracked). Fill in
`source/published_2025.csv` from BEA and BLS, then run `model baselines`. A
real run refuses to start without `data/model/baselines.csv`; synthetic runs
use a made-up placeholder economy.

**Still open for the model.**

- No real run yet, and no `baselines.csv` yet. The checks of the 2025
  identities against official totals pass on the placeholder economy only.
- The industry and occupation code ranges in `make_baselines.py` were written
  without the Census code lists at hand; check them against the lists before
  trusting the tabulation.
- How much compaction costs in coherence within one call is for the first run
  to show. If it hurts, `--split`, or a lookup tool for the definitions (an
  engine change).
- One call is roughly 880,000 output tokens per model (`model prompt`
  estimates it); what that costs is for a smoke run to measure.
- No scoring yet.

## Economic data and resolution

Run these commands from `dashboards/eeai`. The API client reads `FRED_API_KEY`
from the environment or the private forecaster keys file, or a raw key from the
file named by `FRED_API_KEY_FILE`.

```bash
python3 -m eeai replay unemployment 2024 --as-of 2024-02-01
python3 -m eeai replay unemployment 2024 --as-of 2024-02-02
python3 -m eeai replay gdp 2025 --as-of 2025-01-30
python3 -m eeai refresh
python3 -m eeai build
```

Replay inspects the source without storing a decision. The first two examples
should return pending and 3.7%. GDP should round to 2.39%. Refresh retrieves
baseline observations at today's vintage, compares the last original chart
point with the refreshed value, and atomically writes a dated CSV under
`EEAI_RESULTS/baselines`. Original points before the overlap stay as published
in the survey. New runs retain the history they used in their call record.
The page and download share the same baseline snapshot.

Each question selects a dashboard-local resolver and carries its own versioned rule.
The FRED resolver records the earliest vintage covering every input and each
subsequent vintage that changes the computed value. GDP and TFP compound five annual
rates. Labor productivity uses five nonoverlapping Q4 year-over-year rates,
the quarterly convention that best reproduces the original chart. The three
labor-market rates use January. Employment shares combine the specified January
payroll counts and divide by the January labor force. Labor share scales the
Q1 index to the survey's Q1 2023 percentage. Income uses the chart's income
year and converts each real observation to 2023 dollars using the same vintage's
2023 nominal-to-real ratio. Sources with rounding may introduce small differences.

`resolve` runs just the outcome check. Versioned observations and their evidence live in
`EEAI_RESULTS/resolutions.sqlite`; the build includes them in the page and
`resolutions.json` in the download. Forecasts made before rules were recorded
use version 1. When changing a rule, increment its version and retain its
original definition under the question's `previous_rules["1"]`.

The timeline retains the first-release comparison. The outcomes table also
shows the latest revised value, its date and its signed error. Use
`python3 -m eeai replay gdp 2025 --as-of 2026-11-19 --history` to inspect all
distinct vintages without recording them. The page pins `outcome_snapshot_id`;
the ZIP includes the same observations. New forecast rows pin the hash of the
baseline supplied to the model and retain its values in the call record.

Wealth inequality, life satisfaction, AI-assisted hours, AI electricity, and
the end-of-2030 scenario accept a sourced decision under the survey criteria.
Place reviewed releases in `EEAI_RESULTS/reviewed/*.json` for the scheduled resolver,
or use `python3 -m eeai decide FILE.json` to import a decision explicitly. The JSON fields are `question`,
`horizon` (a year string), `version`, `value`, `period`, `vintage` (ISO source
publication date), `source`, `reviewer`, and `rationale`. Cite the source table
or panel decision and explain how it meets the question wording. For the
scenario, use question `ai_scenario`, horizon `2030`, and a survey scenario ID.
A correction also takes `correction_reason` and the prior stored record as
`previous` (the download row without its question and horizon keys). Concurrent
changes reject a stale correction. To correct a revised release, supply that
specific entry from `revisions` as `previous`. Use distinct `revision_id` values
for separate reviewed releases on the same date. Corrections use the explicit
`decide` command and retain the prior evidence.

The schedule in `packages/ops/jobs.json` requests a daily 15:15 UTC economic
refresh and verified site rebuild. It is the automatic ingestion and
resolution trigger for EEAI. Each question's rule controls evidence selection
within that job. The forecast runner reads the last completed local baseline
and makes no FRED requests. The refresh uses existing forecast runs and
makes no model calls. If an upstream resolution check fails, the dated
baseline stays at its last completed version. Frozen decisions are retained
as evidence. Production activation follows the shared deployment
guide and requires FRED access from the scheduled runtime. See the
[EEAI operator pilot](../../packages/ops/DASHBOARDS.md#eeai-operator-pilot)
for scheduler diagnostics, verified refresh and recovery.

New builds report the as-of date of the dated FRED file used for the
baseline. This is the source vintage cutoff for the refresh. The survey seed
has no as-of date. The page data and the ZIP's `baseline.json` describe the
same `history.csv` bytes. A frontend-only deploy keeps the previously
published data block and ZIP, so a legacy publication without baseline
provenance displays an unavailable date. The download card links to the
live site's `release.json`.

## Open

- **Beyond the survey.** The design mock-ups also show a quarterly GDP path, 12
  sector forecasts, AI adoption and macro demand scenarios, and attributed
  forecast updates. None is in the survey; each would be a new instrument
  version, and a new series.
- The AI electricity question points to an embedded document the survey's
  respondents could open and the models cannot.

## Human survey forecasts

Economic charts show two survey medians at each horizon and scenario that
humans answered. The bold filled dot shows superforecasters with their
survey weights. The hollow ring shows the full human panel, including
superforecasters, with one vote per eligible respondent. Both use the lower
median at an exact half-weight tie. All marks share the target year’s x-coordinate. Hovering anywhere along that
year shows the model and human estimates together, including respondent counts. The run-history chart gives the original survey
its own labeled position. Forecast details include counts and elicited ranges.
The AI progress probability table uses the same two panels and their respective
weighted and equal-weight means.

The build reads `eeai/data/human_forecasts.csv`. The page and the download
use the same rounded values and respondent counts. Git retains the history
of this summary. Building a release needs no warehouse access or runtime
survey import.

To refresh the summary, run the two queries under `eeai/warehouse/` against
the EEAI warehouse. Save their results as `economic.csv` and `probabilities.csv`
in a private directory. The queries return weights grouped by response value
and a distinct respondent count per cell. With bq, set the project, use
standard SQL, and pass `--format=csv --max_rows=1000000`. Python checks the
reported extract length, computes the weighted statistics, and rounds values
to the precision shown on the dashboard.

```bash
python3 -m eeai summarize-human "$EXTRACT_DIR" --extracted-on "$EXTRACT_DATE"
```

Review the changed summary values, cohort sizes, and question coverage before
committing the CSV. The dated private runtime snapshots used by earlier releases
are no longer required by the build.
