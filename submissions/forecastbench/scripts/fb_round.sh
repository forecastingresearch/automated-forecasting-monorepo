#!/usr/bin/env bash
# One ForecastBench round, unattended: wait for the question set, run every
# condition's members, retry what failed, build the sets to upload.
#
#   scripts/fb_round.sh 2026-10-11                 # the real round
#   SAMPLE=8 scripts/fb_round.sh 2026-09-27 rehearsal   # a cheap end-to-end check
#
# The machine's settings come from ~/.config/fri-forecaster/round.env (or
# $FORECASTER_ROUND_ENV), sourced with every variable exported; see
# examples/round.env.example. The team's names (FB_ORG, the anonymous one every
# set goes up under; FB_PUBLIC_ORG, its own, for the one condition the registry
# marks public) and the name registry (FORECASTER_NAMES) are private: they live
# there, never in the repo. API keys only, from FORECASTER_ENV_FILE: pi gets
# its own agent dir, never a login.
# Writes $ROUNDS_DIR/<due>[-<tag>]/ and a one-screen summary.txt there.
#
# Submitted conditions have first claim on the shared workers in registry order.
# Each set can validate and upload while other members are still forecasting.
# Run scoring-only conditions after the submissions.
set -uo pipefail

DUE="$1"; TAG="${2:-}"
UPLOAD=0
if [[ "$TAG" == --upload ]]; then UPLOAD=1; TAG=""; fi
HERE="$(cd "$(dirname "$0")/.." && pwd)"
CONF="${FORECASTER_ROUND_ENV:-$HOME/.config/fri-forecaster/round.env}"
if [[ -f "$CONF" ]]; then set -a; source "$CONF"; set +a; fi
: "${FB_ORG:?set FB_ORG (the ForecastBench team name for anonymous sets, Anonymous N) in $CONF}"
ROOT="${ROUNDS_DIR:-$HERE/rounds}/$DUE${TAG:+-$TAG}"
PY="${PY:-$HERE/../../.venv/bin/python}"
SAMPLE="${SAMPLE:-}"
CALLS="${CALLS:-12}"                            # pi calls at once, shared by the members that run together
WAIT_UNTIL="${WAIT_UNTIL:-${DUE}T08:00:00Z}"    # give up waiting for the set after this
if [[ "$UPLOAD" == 1 && ( -n "$SAMPLE" || "$(date -u +%F)" != "$DUE" ) ]]; then
  echo "Automatic upload requires a full round on its UTC due date" >&2
  exit 3
fi

export FORECASTER_ENV_FILE="${FORECASTER_ENV_FILE:-$HOME/.config/fri-forecaster/env}"
export PI_CODING_AGENT_DIR="${PI_CODING_AGENT_DIR:-$HOME/.config/fri-forecaster/pi-agent}"
mkdir -p "$ROOT/logs" "$PI_CODING_AGENT_DIR"
rm -f "$ROOT/logs/paged"

# The submissions, in set-number order, are the registry's submitted
# conditions; the others (OTHERS) only run, for scoring afterwards.
SETS=($("$PY" -m forecastbench.names conditions)) || exit 3
if (( ${#SETS[@]} == 0 )); then echo "No registered submission sets" >&2; exit 3; fi
ALL=($("$PY" -m forecastbench.names conditions --all)) || exit 3
OTHERS=(); for c in "${ALL[@]}"; do [[ " ${SETS[*]} " == *" $c "* ]] || OTHERS+=("$c"); done
PUBLIC="$("$PY" -m forecastbench.names public)" || exit 3
if [[ -n "$PUBLIC" && -z "${FB_PUBLIC_ORG:-}" ]]; then
  echo "the registry submits $PUBLIC under the team's own name: set FB_PUBLIC_ORG in $CONF" >&2; exit 3
fi

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$ROOT/logs/round.log"; }
QSET="$DUE-llm.json"
URL="https://raw.githubusercontent.com/forecastingresearch/forecastbench-datasets/main/datasets/question_sets/$QSET"
log "round $DUE${TAG:+ ($TAG)} -> $ROOT; waiting for $QSET"
until curl -fsI --max-time 30 "$URL" >/dev/null 2>&1; do
  if [[ "$(date -u +%FT%TZ)" > "$WAIT_UNTIL" ]]; then log "gave up: $QSET not published by $WAIT_UNTIL"; exit 2; fi
  sleep 120
done
log "question set is up"

# The panel: the models this machine can run, best by ECI first, as the hook
# `panel_members` prints them (round.env; `<Epoch name> TAB <pi id> TAB <lab>`
# per line; AIRO's `python -m redlines.registry` is one). names.py registers
# the next place for a condition whose members are not the panel's top N or
# whose code drifted, so a round never runs a stale ensemble and never waits
# for a hand step. Without a hook the ranking is Epoch's published index,
# names only: a moved top N is then logged, not registered.
# A hook that fails stops the round (a top model it cannot run, say): nothing
# stands in for the panel.
if declare -F panel_members >/dev/null; then
  PANEL="$(panel_members 2>>"$ROOT/logs/round.log")" \
    || { log "FATAL: the panel could not be read (panel_members failed; see above): the round does not run"; exit 3; }
else
  PANEL="$("$PY" -m fri_forecaster.eci --fetch --names 2>>"$ROOT/logs/round.log")" \
    || { log "FATAL: could not refresh the Epoch index"; exit 3; }
fi
[[ -n "$PANEL" ]] || { log "FATAL: panel selection returned no members"; exit 3; }
log "ECI panel in rank order for this invocation:"
while IFS= read -r row; do log "$row"; done <<< "$PANEL"
SYNC_NOTE="$("$PY" -m forecastbench.names sync --baseline-ensemble <<< "$PANEL")" || { log "names sync failed: $SYNC_NOTE"; exit 3; }
while read -r line; do log "$line"; done <<< "$SYNC_NOTE"

# The first call writes question_set.json; the rest must not race it.
"$PY" -c "from forecastbench import load_question_set; import json; json.dump(load_question_set('$QSET'), open('$ROOT/question_set.json','w'))" \
  || { log "could not fetch $QSET"; exit 2; }

rm -f "$ROOT"/logs/key-refused-*
round_args=()
if [[ "$UPLOAD" == 1 ]]; then round_args+=(--upload); fi
"$PY" -m forecastbench.round_run --root "$ROOT" --due "$DUE" --calls "$CALLS" \
  ${TAG:+--tag "$TAG"} ${SAMPLE:+--sample "$SAMPLE"} ${TIMEOUT:+--timeout "$TIMEOUT"} "${round_args[@]}"
rc=$?

{ echo "ForecastBench round $DUE${TAG:+ ($TAG)} on $(hostname), $(date -u +%FT%TZ)"
  echo "$SYNC_NOTE"
  cat "$ROOT"/logs/build-[0-9]*.log | grep -h "complete\|ready\|NOT READY\|SHORT MEMBER\|forecasts from"
  [[ ${#OTHERS[@]} == 0 ]] || echo "run and kept, not submitted: ${OTHERS[*]}"
  echo; echo "API cost by member:"
  for f in "$ROOT"/members/*/results.jsonl; do
    printf '  %-55s $%s\n' "$(basename "$(dirname "$f")")" \
      "$("$PY" -c "import json,sys; print(round(sum(json.loads(l)['usage'].get('cost_usd') or 0 for l in open(sys.argv[1]) if l.strip()),2))" "$f")"
  done
  echo; ls "$ROOT"/*.json | grep -v question_set
} > "$ROOT/summary.txt"
log "done"; cat "$ROOT/summary.txt"
exit "$rc"
