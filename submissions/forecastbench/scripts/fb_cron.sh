#!/usr/bin/env bash
# Cron's entry for one ForecastBench round. Run the round with per-set uploads
# and page if progress falls behind or the round fails.
#
#   5 0 25 10 * /usr/bin/flock -n /tmp/fb-round.lock <checkout>/scripts/fb_cron.sh 2026-10-25
#
# Settings come from round.env like the round's (see examples/round.env.example);
# the alert goes where the installation's alerts file says (fri_forecaster.alert).
# Output goes to $ROUNDS_DIR/<due>/logs/cron.out.
set -uo pipefail

DUE="$1"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
CONF="${FORECASTER_ROUND_ENV:-$HOME/.config/fri-forecaster/round.env}"
if [[ -f "$CONF" ]]; then set -a; source "$CONF"; set +a; fi
ROOT="${ROUNDS_DIR:-$HERE/rounds}/$DUE"
PY="${PY:-$HERE/../../.venv/bin/python}"
mkdir -p "$ROOT/logs"

rm -f "$ROOT/logs/upload-confirmed" "$ROOT/logs/first-upload-confirmed"
if [[ "$(date -u +%F)" == "$DUE" ]]; then
  env -u FRI_ALERT_LEDGER "$PY" -m forecastbench.status --root "$ROOT" --watch >> "$ROOT/logs/cron.out" 2>&1 &
  delivery_watchdog=$!
  (
    # Progress pages supplement terminal failure alerts from the scheduler.
    unset FRI_ALERT_LEDGER
    timer=""
    trap 'if [[ -n "$timer" ]]; then kill "$timer" 2>/dev/null; fi; exit 0' TERM
    wait_until() {
      local target seconds
      target="$(date -u -d "$DUE $1 UTC" +%s)" || return
      seconds=$((target - $(date -u +%s)))
      if (( seconds > 0 )); then
        sleep "$seconds" &
        timer=$!
        wait "$timer"
        timer=""
      fi
    }
    wait_until 12:00
    "$PY" -m forecastbench.progress --root "$ROOT"
    wait_until 20:00
    if [[ ! -e "$ROOT/logs/upload-confirmed" ]]; then
      "$PY" -m fri_forecaster.alert send --deployment forecastbench --severity page --title 'upload still pending' \
        --log "$ROOT/logs/round.log" "$DUE: some submissions are still pending. Check progress before midnight UTC.
$("$PY" -m forecastbench.status --root "$ROOT")"
    fi
  ) >> "$ROOT/logs/cron.out" 2>&1 &
  watchdog=$!
  trap 'kill "$watchdog" "$delivery_watchdog" 2>/dev/null; wait "$watchdog" "$delivery_watchdog" 2>/dev/null' EXIT
fi

"$HERE/scripts/fb_round.sh" "$DUE" --upload >> "$ROOT/logs/cron.out" 2>&1
rc=$?
if [[ "$rc" != 0 && "$rc" != 4 && ! -e "$ROOT/logs/paged" ]]; then
  why="$(grep -hE 'FATAL|gave up|could not|NOT READY|SHORT' "$ROOT/logs/round.log" "$ROOT/summary.txt" 2>/dev/null | sort -u | tail -2 | cut -c1-200)"
  "$PY" -m fri_forecaster.alert send --deployment forecastbench --severity page --title "run FAILED" \
    --log "$ROOT/logs/round.log" "$DUE: exit $rc, due by 23:59 UTC. $why
Rerun scripts/fb_round.sh $DUE once fixed; what is done is kept." >> "$ROOT/logs/cron.out" 2>&1
fi
exit $rc
