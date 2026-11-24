"""No provider calls: prompt isolation, immutable results and comparison provenance."""
import copy
import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from redlines import experiments, rationale_followup as rf
from redlines.config import CATASTROPHE_RATIONALE_QIDS, POST_FORECAST_PROTOCOL
from redlines.instrument import CURRENT_INSTRUMENT
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_experiments import TestRunOneJoint as RunnerFixture, ru, AIRO
from test_rationale_prompts import build_rows, call_rows


@pytest.fixture
def context():
    groups, by_group, horizons, _, spec = ru.load_batch(ru.LADDER, ru.CROSS, ru.UNBATCHED)
    question = next(q for q in ru.debrief_questions(groups, by_group) if q["id"] == "catastrophe:ai")
    call = {"date": "2026-11-18", "run": "run1", "modelId": "example/model", "condition": "none",
            "instrument": CURRENT_INSTRUMENT, "protocol": "unified-joint-combined-v12",
            "forecasts": {question["id"]: {h: 0.02 for h in horizons}}}
    snapshot = {"date": "2026-11-18", "runs": ["run1"], "sha256": "fixture-digest",
                "questions": {question["id"]: question}, "calls": {"call1": call}}
    args = dict(model="example/model", condition=AIRO["conditions"]["none"], question=question,
                spec=spec, today=date(2026, 11, 20), horizons=horizons)
    return snapshot, args


def test_same_model_condition_horizons_and_repeat_mean(context):
    snapshot, args = context
    repeat = copy.deepcopy(snapshot["calls"]["call1"])
    repeat["forecasts"]["catastrophe:ai"] = dict.fromkeys(args["horizons"], 0.04)
    snapshot["calls"]["call2"] = repeat
    result = rf.comparison(snapshot, **args)
    assert result["available"] and result["repeat_count"] == 2
    assert result["probabilities"] == dict.fromkeys(args["horizons"], 0.03)
    assert result["call_ids"] == ["call1", "call2"]
    assert result["publication_sha256"] == "fixture-digest"
    assert result["elicitation_changed"]
    assert result["previous_resolves_on"]["6mo"] == "2027-05-18"
    assert result["current_resolves_on"]["6mo"] == "2027-05-20"
    assert result["previous_resolves_on"]["2030"] == result["current_resolves_on"]["2030"]
    assert "harm_years" not in json.dumps(result)  # catastrophe is not an incident-onset window


@pytest.mark.parametrize("field,value,reason", [
    ("modelId", "example/other", "exact model"), ("condition", "recent", "prompt condition"),
    ("date", "2026-11-16", "previous forecast"), ("run", "unpublished", "previous forecast"),
    ("instrument", "different", "instrument changed"), ("forecasts", {}, "horizons"),
])
def test_no_substitute_for_missing_or_incompatible_comparison(context, field, value, reason):
    snapshot, args = context
    snapshot["calls"]["call1"][field] = value
    result = rf.comparison(snapshot, **args)
    assert not result["available"] and reason in result["reason"]


def test_changed_question_and_nonprevious_date_are_unavailable(context):
    snapshot, args = context
    snapshot["questions"] = {"catastrophe:ai": {**args["question"], "criteria": "changed"}}
    assert "criteria changed" in rf.comparison(snapshot, **args)["reason"]
    snapshot["date"] = args["today"].isoformat()
    assert "earlier forecast date" in rf.comparison(snapshot, **args)["reason"]
    assert not rf.comparison(None, **args)["available"]


def test_publication_pinned_once_and_missing_file_is_safe(context, tmp_path):
    snapshot, args = context
    timeline = {"snapshots": [{"date": snapshot["date"], "runs": snapshot["runs"]}],
                "questions": list(snapshot["questions"].values())}
    html = f'<script>window.__TIMELINE__ = {json.dumps(timeline)};</script>'
    html += f'<script>window.__RATIONALES__ = {json.dumps({"calls": snapshot["calls"]})};</script>'
    path = tmp_path / "index.html"
    path.write_text(html)
    pinned = rf.publication_snapshot(tmp_path)
    path.write_text("a newer publication")
    assert rf.comparison(pinned, **args)["available"]
    assert len(pinned["sha256"]) == 64
    assert "unavailable" in rf.publication_snapshot(tmp_path)
    path.unlink()
    assert "unavailable" in rf.publication_snapshot(tmp_path)


def test_published_prompts_drop_inline_request_private_experiments_unchanged():
    helper = RunnerFixture()
    rows, seen = helper._call("none", followup_result={"complete": False, "error": "simulated timeout"})
    old, prior = helper._call("none", rationale_mode="inline")
    assert seen["prompt"] == prior["prompt"].replace(
        "a short rationale, the sources you used, and any cells not yet delivered.", "any cells not yet delivered.")
    properties = seen["final_tool"]["parameters"]["properties"]
    assert "rationale" not in properties and "key_sources" not in properties
    assert {r["protocol"] for r in rows} == {POST_FORECAST_PROTOCOL}
    assert [r["forecasts"] for r in rows] == [r["forecasts"] for r in old]
    assert all(r["attempts"] == 1 for r in rows)  # failure must not trigger forecasting again
    assert all(r["rationale"] is None for r in rows)
    assert rows[0]["post_forecast_rationale"]["status"]["error"] == "simulated timeout"
    assert not any(r.get("post_forecast_rationale") for r in rows[1:])
    assert "publication_sha256" not in seen["prompt"]
    assert set(seen["debrief"]["comparisons"]) == set(CATASTROPHE_RATIONALE_QIDS)
    for name in ("prior-recent-shadow", "prior-baseline-shadow"):
        for condition in experiments.load(name)["conditions"].values():
            assert not rf.enabled(condition)
            assert ru.set_protocol(ru.load_policies(ru.COMBINED), condition) == "unified-joint-combined-v12"


def test_validate_before_explaining_requires_headline_cells():
    allowed = {"catastrophe:ai": ["6mo"], **{f"other:{i}": ["6mo"] for i in range(10)}}
    cells = [{"question_id": q, "horizon": "6mo", "probabilities": {"unconditional": 0.01}} for q in allowed]
    args = dict(allowed=allowed, horizons=["6mo"], scenario_ids=[], elicits=[])
    assert ru.validate_before_explanation({"forecasts": cells}, **args) == []
    assert "catastrophe:ai" in " ".join(ru.validate_before_explanation({"forecasts": cells[1:]}, **args))
    cells[0]["probabilities"]["unconditional"] = float("nan")
    assert "finite" in " ".join(ru.validate_before_explanation({"forecasts": cells}, **args))


@pytest.mark.parametrize("delivered,estimate,rejected", [
    (9, {"lower": 0, "upper": 0.5}, False),  # exactly 90% is still accepted
    (8, {"lower": 0, "upper": 0.5}, True),
    (0, {"lower": 0, "upper": 0.5}, True),
    (10, None, True),
    (10, {"lower": 0}, True),
    (10, {"lower": 0.5, "upper": 0.2}, True),
])
def test_shared_submission_checks_preserve_acceptance_rules(delivered, estimate, rejected):
    allowed = {f"example:{i}": ["6mo"] for i in range(10)}
    cells = [{"question_id": qid, "horizon": "6mo",
              "probabilities": {"unconditional": 0.1, "policy": 0.2}}
             for qid in list(allowed)[:delivered]]
    args = dict(allowed=allowed, horizons=["6mo"], scenario_ids=["policy"],
                elicits=[{"key": "estimate", "fields": ["lower", "upper"], "minimum": 0, "maximum": 1}])
    answer = {"forecasts": cells, "estimate": estimate}
    _, _, received, expected, problems = ru.check_forecast_submission(answer, **args)
    assert (received, expected) == (2 * delivered, 20)
    assert bool(problems) == rejected
    assert ru.validate_before_explanation(answer, **args) == problems


def test_followup_schema_validation_and_record(context):
    snapshot, args = context
    qid = args["question"]["id"]
    comparison = rf.comparison(snapshot, **args)
    state = rf.state([args["question"]], {qid: comparison}, validator_file=ru.__file__)
    assert "0.02" in state["prompt"]
    good = {qid.replace(":", "__"): {"level": "Example risk explanation.",
            "change": "The cause of movement is uncertain.", "key_sources": []}}
    assert rf.validate_explanations(good, [qid]) == []
    good["catastrophe__ai"]["key_sources"] = [{"url": "javascript:alert(1)", "contribution": "bad"}]
    assert rf.validate_explanations(good, [qid])
    state.update(result="malformed", complete=False)
    assert rf.record(state, {"forecasts": []})["explanations"] == {}


def test_builder_keeps_followup_from_first_row_and_preserves_originals():
    rows = call_rows("none", "none")
    followup = {"version": "fixture", "explanations": {"second": {"level": "A", "change": "B"}}}
    rows[0]["post_forecast_rationale"] = followup
    before = copy.deepcopy(rows)
    data = build_rows(rows, selected=rows[1:])
    call = next(iter(data["calls"].values()))
    assert call["postForecast"] == followup
    assert call["rationale"] == "Original batch rationale."
    assert rows == before


def test_capability_tab_accepts_new_protocol_rows():
    from redlines.views import capability
    rows = [{"protocol": POST_FORECAST_PROTOCOL, "run_date": "2026-11-20",
             "instrument_version": CURRENT_INSTRUMENT, "scenario": None}]
    with patch.object(capability, "latest_conditional", return_value=rows), patch.object(capability, "log_exists", return_value=True):
        _, selected_rows, _, _, _, protocol = capability._pick([("data/combined_conditions.json", "capability")])
    assert selected_rows == rows
    assert protocol == POST_FORECAST_PROTOCOL
