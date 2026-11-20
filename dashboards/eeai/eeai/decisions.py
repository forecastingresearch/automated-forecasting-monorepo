"""Record a sourced human decision or a reviewed correction from a JSON file."""
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

from . import config, survey
from dashboard import resolutions


def validate(decision, today, doc):
    qid, horizon = decision["question"], decision["horizon"]
    year = int(horizon)
    value = decision["value"]
    if qid == "ai_scenario":
        rule = doc["scenarios"]["resolution"]
        if horizon != "2030" or value not in [s["id"] for s in doc["scenarios"]["items"]]:
            raise ValueError("Expected a 2030 survey scenario")
        unit = "scenario"
    else:
        q = next((q for q in doc["questions"] if q["id"] == qid), None)
        if not q or horizon not in [h["id"] for h in q["horizons"]]:
            raise ValueError("Unknown question or horizon")
        rule, unit = q["resolution"], q["unit"]
        if decision["version"] != rule["version"]:
            rule = q.get("previous_rules", {}).get(str(decision["version"]))
            if not rule:
                raise ValueError("Unknown resolution rule version")
        if rule["method"] != "adjudicated" and "previous" not in decision:
            raise ValueError("This question resolves automatically")
        if type(value) not in (int, float) or not math.isfinite(value) or not q["bounds"][0] <= value <= q["bounds"][1]:
            raise ValueError("Invalid outcome value")
    vintage = date.fromisoformat(decision["vintage"])
    earliest = date(year + 1, 1, 1) if qid in ("ai_scenario", "ai_electricity", "life_satisfaction", "wealth_inequality", "median_household_income") else date(year, 1, 1)
    if not earliest <= vintage <= today or decision["version"] != rule["version"]:
        raise ValueError("Invalid evidence date or resolution rule version")
    fields = ("source", "rationale", "reviewer", "period")
    if not all(isinstance(decision.get(f), str) and decision[f].strip() for f in fields):
        raise ValueError("Decision requires source, rationale, reviewer and measurement period")
    outcome = {k: decision[k] for k in (*fields, "value", "vintage")}
    outcome["unit"] = unit
    return resolutions.Target(qid, horizon, rule["version"]), rule, outcome


class ReviewedResolver:
    """Import independent cited releases from the dashboard's private review directory."""
    def __init__(self, directory, doc):
        self.directory = directory
        self.doc = doc

    def refresh(self, requests, *, as_of, after):
        targets = {r.target for r in requests}
        observations = []
        for path in sorted(self.directory.glob("*.json")):
            decision = json.loads(path.read_text())
            if "previous" in decision:
                raise ValueError("Apply a processing correction with eeai decide")
            if date.fromisoformat(decision["vintage"]) > as_of:
                continue
            target, _, evidence = validate(decision, as_of, self.doc)
            if target not in targets:
                raise ValueError(f"Unexpected reviewed target {target}")
            vintage = evidence.pop("vintage")
            observations.append(resolutions.Observation(target, decision.get("revision_id", vintage), vintage,
                                                       evidence.pop("value"), evidence))
        return resolutions.RefreshBatch(observations, {})


def apply(path, today=None):
    decision = json.loads(Path(path).read_text())
    target, rule, outcome = validate(decision, today or datetime.now(timezone.utc).date(), survey.load())
    qid, horizon, _ = target
    db = config.RESULTS / "resolutions.sqlite"
    if "previous" in decision:
        resolutions.correct(db, qid, horizon, rule, outcome, previous=decision["previous"],
                            reason=decision["correction_reason"])
    else:
        resolutions.record(db, qid, horizon, rule, outcome, revision=decision.get("revision_id"))
