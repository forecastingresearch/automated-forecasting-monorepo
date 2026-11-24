# Post-forecast catastrophe explanations

The published `airo` experiment opts into `rationale_mode = "post-catastrophe-v1"`.
Its five pooled conditions use elicitation protocol `unified-joint-combined-v13`:

1. Research and submit the existing forecast grid and ECI distribution, without
   requesting an inline rationale or supplying a previous forecast.
2. Validate the submission, save `final.json`, and lock both final and partial
   forecast submission tools. A late tool call in the same turn cannot overwrite
   a previously submitted cell.
3. In the same conversation, ask only about the unconditional AI and general
   catastrophe questions: **A, the absolute risk level; B, the change since the
   previous published forecast**. Research tools are closed. Explanations are
   retrospective accounts, not evidence of what caused numerical movement.

The scenario-set JSON keeps its original v12 tag because its questions and
scenarios are unchanged. `run_unified.set_protocol(policies, condition)` supplies
v13 only for the opted-in published conditions. The condition hash also changes.
Manual/unpooled conditions and the separate prior-recent/rationale-revision
experiment keep their original prompts, hashes and protocol.

## Previous-forecast comparison

The runner reads the existing `--prior-publication` / `AIRO_PRIOR_PUBLICATION`
directory once, before workers start. This is the previously published site,
not the newest raw run or an experimental prior. Its public timeline and
rationale data are hashed; the exact comparison payload is archived with the
follow-up. The local directory path is not exported.

Match the latest published date and run, exact model ID, prompt condition,
question wording/criteria, instrument and horizons. Average repeats only within
that model/condition. A missing or incompatible match yields an explicit
unavailable comparison; it never substitutes another model or an older date.
Still request the absolute-level explanation. Both resolution dates are saved,
and rolling-horizon changes and the initial elicitation-method change are flagged.
Legacy endpoint dates are reconstructed from the matched instrument and labelled
as such in the archived comparison. Catastrophe measurement rules are distinct
from the incident ladder's onset windows.

## Failures, records and display

The existing bounded debrief loop retries only the explanation. Timeout, refusal,
malformed output or validation failure leaves accepted forecasts intact; none
causes a fresh forecasting attempt. Follow-up validation errors cannot mark an
answer complete. Invalid forecast submissions are corrected before the previous
forecast context is revealed.

The first row of each call stores `post_forecast_rationale`: version, exact prompt,
comparison/source IDs and hash, submitted-answer hash, explanations and completion
status. Every row carries `rationale_mode` and the new forecast protocol. These
records remain in the original JSONL downloads; legacy fields are preserved.

The website retains its condition/model buttons and single forecast row. It
shows A/B for the catastrophe questions, with expandable sources, previous
numbers/dates, prompts and provenance. Old records are labelled historical, and
incomplete follow-ups have an explicit missing-explanation state. No historical
explanation is rewritten or backfilled. Severity-ladder explanations are removed
from the visible panel; their original records remain in the download.

The frontend can be reviewed immediately. Genuine A/B answers will first appear
after deployment and a new scheduled forecast run; no paid run is needed to test
or deploy the frontend. A normal frontend deployment preserves the currently
published snapshot. The next validated data publication supplies the new fields.

## Validation

No new dependencies. The existing pytest and pinned pi test tools are sufficient.
From the repository root, after installing the workspace and its test tools:

```sh
npm ci --prefix packages/forecaster
pytest dashboards/airo/tests packages/forecaster/tests
```

The local scripted-model tests exercise the real pi engine without provider
calls: hidden previous context, rejected invalid finals, same-turn writes after
locking, bounded explanation failure and preservation after timeout. AIRO tests
cover exact comparison matching, endpoint dates, missing prior data, archived
metadata, versioning and unchanged private experiments.
