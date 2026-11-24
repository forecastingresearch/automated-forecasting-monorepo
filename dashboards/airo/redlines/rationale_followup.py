"""Post-submission explanations and a pinned, like-for-like published comparison.

Nothing from this module's comparison is inserted into the forecast prompt.
The harness reveals it only after saving final.json and disabling submissions.
"""
import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path
from statistics import mean

from redlines.config import (CATASTROPHE_RATIONALE_QIDS, POST_FORECAST_RATIONALE,
                             RATIONALE_RETRIES)
from redlines.questions import resolves_on


def enabled(condition):
    return condition.get("rationale_mode") == POST_FORECAST_RATIONALE


def publication_snapshot(publication):
    """Read once before workers start; unavailable input never blocks a forecast.

    Keep the public evidence in memory, not a mutable path for workers to reread.
    Its digest and the exact comparison payload are archived with each answer.
    """
    if not publication:
        return {"unavailable": "No previous publication was supplied."}
    try:
        html = (Path(publication) / "index.html").read_text()
        blocks = {}
        for key in ("TIMELINE", "RATIONALES"):
            match = re.search(r'window\.__' + key + r'__\s*=\s*(.*?);\s*</script>', html, re.S)
            if not match:
                raise ValueError("missing published data")
            blocks[key] = json.loads(match[1])
        latest = max(blocks["TIMELINE"]["snapshots"], key=lambda s: s["date"])
        date.fromisoformat(latest["date"])
        calls = blocks["RATIONALES"]["calls"]
        if not isinstance(calls, dict) or any(not isinstance(c, dict) or
                not isinstance(c.get("forecasts", {}), dict) or any(not isinstance(f, dict)
                for f in c.get("forecasts", {}).values()) for c in calls.values()):
            raise ValueError("invalid published calls")
        return {"date": latest["date"], "runs": latest["runs"],
                "questions": {q["id"]: q for q in blocks["TIMELINE"]["questions"]},
                "calls": calls,
                "sha256": hashlib.sha256(json.dumps(blocks, sort_keys=True).encode()).hexdigest()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {"unavailable": "The previous publication could not be read or verified."}


def comparison(snapshot, *, model, condition, question, spec, today, horizons):
    """Match the latest published date, exact model/condition/question and horizons.

    Never substitute another model, a pooled number, or an older matching date.
    Repeat calls are averaged within that one model and prompt condition.
    """
    snapshot = snapshot or {"unavailable": "No previous publication was supplied."}
    result = {"available": False, "current_date": today.isoformat(),
              "current_resolves_on": {h: resolves_on(h, today, spec) for h in horizons}}

    def unavailable(reason):
        return {**result, "reason": reason}

    if snapshot.get("unavailable"):
        return unavailable(snapshot["unavailable"])
    result.update(date=snapshot["date"], publication_sha256=snapshot["sha256"])
    if snapshot["date"] >= today.isoformat():
        return unavailable("The supplied publication is not from an earlier forecast date.")
    qid = question["id"]
    previous_question = snapshot["questions"].get(qid, {})
    if any(previous_question.get(k) != question.get(k) for k in ("text", "criteria")):
        return unavailable("The question wording or resolution criteria changed.")
    calls = {cid: c for cid, c in snapshot["calls"].items()
             if c.get("date") == snapshot["date"] and c.get("run") in snapshot["runs"]
             and c.get("modelId") == model and c.get("condition") == condition["id"]}
    if not calls:
        return unavailable("No previous forecast for this exact model and prompt condition.")
    if any(c.get("instrument") != spec.get("instrument_version") for c in calls.values()):
        return unavailable("The forecast instrument changed.")
    estimates = [(c.get("forecasts") or {}).get(qid, {}) for c in calls.values()]
    if any(set(e) != set(horizons) or any(type(v) not in (int, float) or not math.isfinite(v)
            or not 0 <= v <= 1 for v in e.values()) for e in estimates):
        return unavailable("Previous forecast horizons are missing or incompatible.")
    # Catastrophes have their own five-year accumulation rule; do not borrow
    # the incident ladder's three-year onset windows. Legacy published calls
    # lack resolvesOn, so reconstruct endpoints using the matched instrument.
    previous_dates = {h: resolves_on(h, date.fromisoformat(snapshot["date"]), spec) for h in horizons}
    if any(c.get("resolvesOn") and any(c["resolvesOn"].get(h) != previous_dates[h] for h in horizons)
           for c in calls.values()):
        return unavailable("Previous resolution dates are incompatible with the current horizons.")
    return {**result, "available": True, "call_ids": sorted(calls), "repeat_count": len(calls),
            "probabilities": {h: mean(e[h] for e in estimates) for h in horizons},
            "previous_resolves_on": previous_dates,
            "dates_reconstructed": any(not c.get("resolvesOn") for c in calls.values()),
            "previous_protocols": sorted({c.get("protocol") or "unrecorded" for c in calls.values()}),
            "elicitation_changed": any(c.get("rationaleMode", "inline") != POST_FORECAST_RATIONALE
                                       for c in calls.values())}


def validate_explanations(value, qids):
    if not isinstance(value, dict):
        return ["Submit an object with one entry per catastrophe question."]
    problems = []
    for qid in qids:
        entry = value.get(qid.replace(":", "__"))
        if not isinstance(entry, dict):
            problems.append(f"{qid}: missing explanation")
            continue
        for field in ("level", "change"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                problems.append(f"{qid}: {field} is missing")
        sources = entry.get("key_sources")
        if not isinstance(sources, list) or any(not isinstance(s, dict) or
                not isinstance(s.get("url"), str) or not re.match(r"^https?://", s["url"]) or
                not isinstance(s.get("contribution"), str) or not s["contribution"].strip() for s in sources):
            problems.append(f"{qid}: key_sources must be a list of URLs and contributions (or [] if none)")
    return problems


def state(questions, comparisons, *, validator_file):
    qids = [q["id"] for q in questions if q["id"] in CATASTROPHE_RATIONALE_QIDS]
    schema = {"type": "object", "additionalProperties": False, "properties": {
        "level": {"type": "string", "description": "A: Why this absolute catastrophe risk?"},
        "change": {"type": "string", "description": "B: Why the change, or why comparison is unavailable?"},
        "key_sources": {"type": "array", "items": {"type": "object", "properties": {
            "url": {"type": "string"}, "contribution": {"type": "string"}},
            "required": ["url", "contribution"]}}}, "required": ["level", "change", "key_sources"]}
    prompt = (
        "Your submitted forecasts have been saved and locked. Do not revise any numbers. "
        "Now call submit_catastrophe_explanations, covering ONLY the unconditional catastrophe "
        "questions listed below, across their horizons. These are your own forecasts under the "
        "selected prompt condition, not the pooled chart average. For each question provide:\n"
        "A (level): 2-4 plain sentences explaining the absolute risk: the main mechanisms, "
        "evidence or base-rate anchors, and the main uncertainty.\n"
        "B (change): 2-4 sentences comparing your locked numbers with the supplied previous "
        "published forecast for the same model and prompt. Identify evidence or assumptions "
        "that could explain movement; explicitly say when the cause is uncertain. A numerical "
        "difference alone is not evidence of a cause. Do not invent news, a previous rationale, "
        "or a causal attribution. Mention an unchanged forecast when appropriate. Account for "
        "the changed forecast date and resolution dates, especially rolling 6/12-month endpoints, "
        "while retaining the catastrophe question's own measurement-window rule, "
        "and any flagged elicitation change. If comparison.available is false, say comparison "
        "is unavailable and why; still provide A.\n"
        "key_sources: only sources already read or seen in this conversation, with what each "
        "contributed; [] when none. No new research. Keys use '__' in place of ':'. "
        "These are retrospective explanations, not proof of what caused the forecasts.\n\n"
        + json.dumps({q: comparisons[q] for q in qids}, ensure_ascii=False, sort_keys=True))
    return {"tool": {"name": "submit_catastrophe_explanations",
                     "description": "Explain the locked catastrophe forecasts: level and change.",
                     "parameters": {"type": "object", "properties": {
                         q.replace(":", "__"): schema for q in qids},
                         "required": [q.replace(":", "__") for q in qids]}},
            "prompt": prompt, "retries": RATIONALE_RETRIES, "comparisons": comparisons,
            "validator": {"file": validator_file, "function": "validate_catastrophe_explanations",
                          "kwargs": {"qids": qids}}}


def record(followup, answer):
    """Archive follow-up separately; no historical rationale is relabelled."""
    result = followup.get("result")
    return {"version": POST_FORECAST_RATIONALE, "prompt": followup["prompt"],
            "forecast_sha256": hashlib.sha256(json.dumps(answer, sort_keys=True).encode()).hexdigest(),
            "comparisons": followup["comparisons"],
            "explanations": {k.replace("__", ":"): v for k, v in result.items()} if isinstance(result, dict) else {},
            "status": {k: followup.get(k) for k in ("complete", "attempts", "problems", "error")}}
