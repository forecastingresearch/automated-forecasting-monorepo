# Production releases

AIRO, EEAI and RSI use the production runtime. See [deploying and scheduling dashboards](DASHBOARDS.md) for per-site setup, protected HTTPS, shared panels and the host timer.

On a configured cell, say **deploy** after merging the work. The agent runs
`airo deploy`, then `airo status` and checks the configured public URL. Deployment
is explicit; pushing or merging does not change production by itself.

`airo deploy` fetches `main`, resolves an exact commit, requires all four GitHub
Actions checks on that commit, installs a separate Python environment and the
locked npm dependencies, and combines the new frontend with the existing published
forecast snapshot. All thirteen data blocks, including their question wording,
instrument labels and methodology, and all forecast downloads stay byte-identical.
No forecast jobs run during deployment. A successful activation switches code,
website and schedules together.
The development checkout is never served or run by the production scheduler.

Historical publication validation reconstructs the panel from its recorded Epoch
snapshot and the capability prompt from the Epoch vintage named in the retained
prompt. It recovers the search backend only when the complete saved condition
hash matches exactly. The audit report records both snapshot hashes and recovered
settings. Missing snapshots, unknown settings, altered prompts and incomplete
forecast grids still block publication; today's refreshed inputs never replace
the inputs of an old run during validation.

The live release fetches, checks and checks out the commit; the candidate then
builds itself with its own copy of `code/production.py` (`build-release`, which
only `deploy` calls). So a commit that moves files or changes the build deploys
without the live release knowing how. A commit from before this is built by the
live release, as before.

Commands:

- `airo status`: selected commit, schedules, and recent run receipts.
- `airo deploy [--commit FULL_SHA]`: deploy a checked commit reachable from main,
  publishing the new interface with the currently published data. Missing,
  duplicated or incompatible data-block markers fail closed. Snapshot hashes
  detect unexpected data changes and release metadata tracks frontend and data
  provenance separately. Data schema changes need an explicit migration or a
  validated data publication; they must not silently substitute repository data.
- `airo deploy --publish-data`: rebuild the publication from a private copy of
  accrued forecast data. The existing current-instrument integrity checks must
  pass; failure retains the current code and website without fallback. This
  command does not generate forecasts. Scheduled forecast jobs still validate
  new data before publishing. Use this mode for the first fresh publication.
- `airo deploy --keep-publication`: explicitly deploy code and schedules while
  retaining the last good website. Use for a migration or instrument transition
  when deliberately retaining the whole site; this does **not** publish frontend changes. The first
  migration requires a verified private `bootstrap_publication` path. Release
  metadata records the preserved publication separately from the code commit.
  Ordinary deploys never silently fall back when an integrity check fails.
- `airo rollback`: select the previous code and website; keep accrued data.
- `airo smoke --run-id NAME`: exercise the job runner without calling providers.
  Repeating the same run ID does not execute twice.

The scheduler is `packages/ops/production.py`. The installation's `airo` wrapper
is pinned to `code/production.py` in the live release, so that path stays as a
two-line launcher. Paths below such as `code/cron_run.sh` are AIRO's, under
`dashboards/airo/`. A private configuration file selected by
`AIRO_RUNTIME_CONFIG` (default `~/.config/airo/runtime.json`) supplies `root`,
`repository`, `github_repository`, `path` and the Unix `socket`. Do not commit
machine names, environment files, credentials, production data, or receipts.
The installer provides an `airo` wrapper, a persistent serving service and a
systemd timer that calls `airo tick` each minute. Both run inside the cell as the
agent user; the host ingress forwards only public static requests to the socket.
Use Node 22.21 or newer for native environment-proxy support; the runner enables
`NODE_USE_ENV_PROXY` for forecasting. Keep the production toolchain on the private
configured PATH. No supervisor credentials are needed for subsequent deployments.

Under the private runtime root:

- `releases/`: fixed code, dependency environments, package inventories and sites.
- `current`, `previous`: atomic release pointers.
- `state/results`: accrued production results, shared across releases.
- `state/data`: fetched Epoch snapshots, model registrations and generated conditions.
- `home/`: separate forecasting configuration, name registry, round history and logs.
- `runs/`, `logs/`: durable job receipts and diagnostics.

The initial migration must seed the state from the existing production server,
including licensed fonts. Repository results seed missing files, but never
replace accrued data. Corrections to existing production data require a separate,
reviewed data migration. Dependency versions resolved by pip are recorded per
release; npm uses its checked-in lockfile. Rollback reuses installed environments.
Development and production should use separate VMs/filesystems so development
cannot exhaust production storage. Separate directories on the same filesystem
do not provide that isolation. Keep development checkouts and coding credentials
off the production VM; copy only the runtime, forecasting credentials and data.

Deployment prunes disposable releases before building and after activation.
The current and previous releases are always preserved, plus recent candidates
up to `keep_releases` (default 3, minimum 2). Sites referenced by retained releases
are preserved, including publications produced by jobs. The latest unreferenced
job publication is also retained for diagnosis. Unknown directory names and
symlinks are left alone. `state/`, `home/`, run receipts and logs are never pruned.
Run `airo prune` to apply the same retention policy explicitly. Keep backups of
accrued data independently; release retention is not a backup policy.

Before installing dependencies or starting paid jobs, the runtime checks free
bytes and inodes. Deployment requires at least `min_free_bytes` (default 5 GiB),
or estimated staging space plus a 2 GiB reserve, whichever is larger. This is a
preflight estimate, not a quota; unexpected dependency or forecast growth can
still exceed it. `airo status` includes filesystem usage. `airo storage` prints
usage and exits nonzero below the free-space floor or at 80% byte/inode usage.
Run it from a five-minute systemd timer and monitor failures. Monitor development
storage independently on its own VM; a healthy production disk says nothing
about the development disk.

Dashboard publication streams the historical logs and sorts CSV exports in a
bounded SQLite cache backed by temporary files beside the output, rather than
in a potentially memory-backed system temporary directory. Policy and capability
views retain only their selected day/protocol. Validation hashes logs in chunks.
The publisher builds each view in a fresh process with a 2048 MiB address-space
limit (`AIRO_BUILD_MEMORY_MIB` overrides it) and logs elapsed time and peak RSS.
A memory-limit failure stops publication and retains the last good site.

If forecasts completed but publication failed, inspect the run receipt and
`home/logs/forecast-<stamp>.log`. Fix the build, merge through the normal checks,
and run `airo deploy --publish-data` to validate and publish the saved forecasts;
do not repeat the paid forecast job. `airo status` lists receipts newest first
by their start timestamp, including failures.

## Keys

Every API key the installation holds is in one file in the runtime's private
home, `.config/fri-forecaster/env` (mode 0600, `KEY=value` lines): the model
providers', the search key and the news classifier's. Every job reads it
(`FORECASTER_ENV_FILE`), through `fri_forecaster.keys`, so two jobs cannot hold
different keys for one provider. `python -m fri_forecaster.keys` prints the
names it holds, never a value. A model whose lab's key is not in the file is
left out of the ensemble; a key that is there and refused fails the run.

## Scheduling

ForecastBench scheduling is paused: `jobs.json` contains no ForecastBench jobs.
Keep future rounds unscheduled until an explicit decision to resume. The round
runner, validation, upload, and recovery tooling remain available.

Change `packages/ops/jobs.json` and merge/deploy it. The daily UTC wake-up delegates
experiment selection to `experiments/*.toml`; days with nothing due make no paid
calls. ForecastBench entries have explicit years and due dates. Creating a new
round means adding an entry, reviewing its cost/configuration, and deploying.
Successful rounds upload their validated submission sets automatically with a
dedicated service account; configure it using `submissions/forecastbench/README.md`.
After deploying the upload-capable release, use `airo configure-forecastbench
--upload-prefix gs://bucket/team-prefix/binary` with the service-account JSON
key on stdin. The command validates authentication and stores the key/settings
under the runtime's private home with restricted permissions. Verify write/read
access with `airo check-forecastbench-upload --due YYYY-MM-DD`; this uses a test
`.txt` object, never forecasts or provider calls.
What a round submits, and under
which of the team's names, is the private name registry's
(`submissions/forecastbench/ROUND.md`): at most three sets, at
most one of them public.

In queue mode the minute timer records each scheduled occurrence in the
dashboard's private SQLite database under a unique job-and-time key. A
host-wide forecast worker runs one paid job at a time. A separate refresh
worker serves both news polls and economic-data refreshes. ForecastBench
manages its own model concurrency within its forecast job. A long round can
therefore overlap a news poll or an economic refresh.

The default latest start for paid work is the end of its scheduled UTC minute.
Refreshes have a two-hour start window. An occurrence that times out before
starting is recorded as expired. An interrupted paid run requires operator
inspection. A free news poll can retry up to twice, five minutes apart, while
it remains fresh. EEAI publication retries use the existing verified-refresh
command and its saved candidate. Each worker pins the release and private
staging data it uses. A publishing job checks the active release and previous
site before selecting a candidate. See [worker installation and migration](DASHBOARDS.md#schedule-and-recover-runs).

**Alerts.** Every job alerts through one sender, `fri_forecaster.alert`: a caller
says what happened (`page`: someone must act; `notice`: degraded, no deadline),
and the installation's private `alerts.json`
(`~/.config/fri-forecaster/alerts.json` under the runtime home) says where it
goes. Deployment refuses a release when that file has no channel that takes
every page (`python -m fri_forecaster.alert check`; `... alert test` sends one
line down each channel).

Pages, for every dashboard: **run FAILED** and **publish FAILED** (the run
succeeded). The scheduler sends them for any job that failed without paging
itself, was interrupted, or expired before starting. `scheduled_runs` in
`airo status` shows the scheduled time, latest start, lane, attempts, and
outcome. Workers send expiry notices from the durable queue after dispatch. A failed
notification remains pending for a later delivery attempt. The alert identifies
a job that never started. Existing
receipts retain their original status. A job can send a more specific alert
for a refused key or an incomplete submission. The ensemble is the top four by ECI of the models the installation
holds an API key for; a model whose lab's key is not held is left out until
there is one. A run fails when any member of that ensemble cannot be reached:
one that cannot be run, or one whose calls fail. No other model stands in.
ForecastBench pages **upload FAILED** on authentication, validation or upload
failure, and sends a notice when submissions are confirmed uploaded. Fix an
upload failure with the upload-only command in `submissions/forecastbench/README.md`;
do not rerun paid forecasts.
It pages at noon UTC if the first set is below the coverage needed to be on
pace for an 18:00 UTC target. It pages **upload still pending** at 20:00 UTC if a running round has
yet to confirm its upload. The scheduled round uploads before running
conditions kept only for scoring.

Notices: **condition failed** (outside the published number), **ECI fetch
failed** (the forecast job stops), **news fetch failed**, **ensemble
changed**. Apart from the ForecastBench upload confirmation, nothing is sent on
success, and nothing on the box can report that
the box is down: watch that from outside. To start scheduling after migration, create the private
`jobs-enabled` file only after disabling the old server's corresponding jobs.

The website is published into a new directory. A frontend deploy verifies its
published data blocks and downloads are unchanged; a data publication must pass
the full instrument validation. Only then is the release switched. Failed builds leave the selected release alone. Failure to
observe a new release through the serving socket automatically restores the
previous release. Forecast jobs retain their raw data even if publication fails.

## Friday recent-news shadow: production handoff

The `recent-shadow-noairo` condition in `experiments/airo.toml` runs on Fridays
through the existing 12:00 UTC AIRO dispatcher. It inherits the same refreshed
ECI panel, full instrument, model reasoning settings and harness as the other
AIRO conditions. It is **unpublished and unpooled**; its rows go to private
`state/results/experiments/` rather than changing dashboard numbers. The old
published conditions and their hashes do not change. The manual experiment
alias remains available, but the scheduler uses the AIRO condition.

There is no forced-turn submission cap (`max_turns = 0`). In particular this
job does not invoke `code/probe_recent_news.py`, use Haiku/Sonnet-only models,
truncate the instrument, or inherit the probe's eight-turn/three-minute limits.
The normal production process timeout (three hours unless configured otherwise)
and failure/retry policy still apply.

### Prerequisites before enabling the release

1. Provide `TYPESAFE_API_KEY` in the installation's keys file (see Keys
   above). Do not copy
   a coding-provider login; this is the Jev classifier's API key only.
2. Have the host operator grant the configured feed hosts and `api.typesafe.ai`:
   `www.ft.com`, `www.nytimes.com`, `rss.nytimes.com`, `news.google.com`,
   `arstechnica.com`, `www.technologyreview.com`, `www.theverge.com`. Publisher
   redirects may require additional observed grants such as `www.reuters.com`.
   Use the configured HTTPS proxy. A repository change cannot grant network
   access. Check access in the production cell, not just development.
3. The runtime supplies `AIRO_NEWS_DIR = <runtime root>/state/recent-news`, so
   items, decisions and frozen inputs survive releases and stay outside git.
   Start with a clean live collection; do **not** seed it with the old October
   experiment and present that as current news. RSS history is bounded: the
   first Friday's seven-day window is not guaranteed to contain every story.
4. Merge through normal PR/check requirements, then run `airo deploy` in the
   production cell. Use the normal frontend-with-preserved-data deployment,
   not `--publish-data`, and verify the retained data hash/new frontend commit,
   `airo status`, and the configured public URL. `airo smoke` is sufficient
   for runner testing; do not launch a paid panel just to test deployment.

### Scheduled flow and failure handling

- `packages/ops/jobs.json` adds `recent-news-poll` at **11:45 UTC daily**. This calls
  `code/recent_news.py poll` only: no Jev, Tavily or forecasting-model charges.
  Standard job receipts/logs record failed feeds. It never publishes the site.
- Before the Friday shadow group, `code/prepare_recent_news.py` polls again,
  requires every configured feed to return nonempty parseable data, reduces
  the collection with Jev, and freezes the preceding seven days into one
  hash-pinned, feed-only snapshot shared by every model. **Jev calls incur
  charges.** Ordinary conditions return from this preparation step immediately,
  without accessing feeds or Jev.
- The model receives precisely the owner-approved addition in
  `experiments/recent-news/SHADOW.md`, plus the existing no-AIRO instruction.
  The existing URL guard is applied to web tools and to source URLs included
  in the snapshot. All cache reads are recorded through `read_page`; each row
  carries the snapshot hash and window, never its private filesystem path.
- A missing key, feed error, undecided reduction or empty window skips the
  shadow group and notifies through the normal cron alerts. There is **no old
  snapshot fallback** and no forecast without the cache. Other AIRO conditions
  and normal publication continue. A forecast failure in the standalone
  unpublished group is likewise reported without withholding the main series.

To inspect the scheduled groups offline (no provider calls):

```sh
python3 -m redlines.experiments due --date 2026-10-23
python3 code/run_unified.py --experiment airo \
  --condition recent-shadow-noairo --dry-run
```

The Friday listing must contain both the ordinary six-condition published
group and `airo aside recent-shadow-noairo`. The Wednesday listing must not
contain the news shadow. These commands do not verify live RSS/Jev access;
review the first poll receipt and the Friday shadow's snapshot/evidence logs.

The daily AIRO dispatcher checks experiment cadence before storage preflight or
launching the forecasting runner. An off-day records `skipped` without building a
site or paging. Missed-start checks also consult cadence for the scheduled UTC
date, so scheduler downtime on an off-day does not page. A due job whose schedule query or storage preflight fails records
`failed` with stage `preflight FAILED`, retains the reason in its private log, and
pages once; it is not later misreported as a missed start or retried automatically.

Due forecasts prune disposable releases and publications before checking space.
Scheduled jobs reuse installed code and shared state; their preflight reserves
twice the current site size for a publication plus 2 GiB headroom, subject to the
configured free-space floor. Deployments still reserve their code and data copies.

`airo forecastbench-status [--due YYYY-MM-DD] [--history]` reads per-set
progress and verified delivery receipts while a round is running. The scheduler
requires a matching receipt for every registered submission before recording a
successful ForecastBench job.

### ECI reference projection

`eci-upstream` checks Peter Wildeford's upstream repository daily at 11:30 UTC.
It compares the projection source with the reviewed SHA-256 pinned in
`redlines/eci_trend.py`; data-only commits do not require approval, but source
changes trigger a notice and require review. No upstream Python is executed.

Every AIRO **data publication** calls `python -m redlines.eci_trend` after
instrument validation and before building the site. This includes scheduled
publications and `airo deploy --publish-data`, regardless of weekday or time.
Changing the forecast schedule requires no change to this hook. Frontend-only
deployments and republication of an existing snapshot preserve that snapshot.

The calculation follows upstream commit
`b436a09c09c951b36df1f74ce4db0bed4900523e` (two-segment piecewise-linear fit,
lognormal pace with split 80% interval, normal position uncertainty), restricted
to released US models to match AIRO's question. It uses the latest Epoch snapshot,
one frontier point per release date, and deterministic Monte Carlo draws.
`data/eci_trend_current.json` and `eci_trend_status.json` persist in runtime state.
Refresh/check failures retain the last good curve, send a deduplicated notice,
and mark the next publication stale. The browser also marks a projection more
than seven days old stale, even if publication has stopped. Instrument-integrity
failures still block publication entirely.

To approve an upstream change, review the pinned source against the new source,
update the independent calculation and its tests if necessary, then update both
`COMMIT` and `SOURCE_SHA256` in `eci_trend.py` through normal PR/check/deploy.
