"""The economy model's instrument: what each call asks, its prompt, the answer tools, the cleaning.

By default one call per model asks for everything: the 2025 baselines, the
scenario probabilities, and every component for every scenario and year. The
agent delivers with submit_cells in as many pieces as it likes; pi compacts
the conversation as it fills, and every piece is kept on disk, so the size of
the answer is not limited by the context. calls(split=...) breaks the
elicitation into a few calls instead, should a run show that compaction hurts.

Every component is a question: its answer is a cell {question_id, forecasts:
{year: {scenario: {q05, q25, q50, q75, q95}}}}; a 2025 baseline answers under
year 2025 and scenario "base". A rationale is a cell too, {question_id:
"why....", rationale}, one per group (spec.rationale_groups). As in the
survey, nothing in the prompt advises the model how to forecast (the Baseline
condition, fri_forecaster.baseline).
"""
import csv
import math

from .. import config
from . import spec as M

SPLITS = (None, "scenario", "block")
# Output tokens a quantile set costs in a submit_cells call, roughly: five
# named numbers, the year and scenario keys, the JSON around them.
TOKENS_PER_SET = 45


# ── what each call asks ──────────────────────────────────────────────────────

def calls(spec, split=None):
    """-> [{id, baseline, probabilities, scenarios, blocks}]. One call by default."""
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}")
    blocks = [b["id"] for b in spec["blocks"]]
    scen = M.scenario_ids(spec)
    if split is None:
        return [{"id": "all", "baseline": True, "probabilities": True, "scenarios": scen, "blocks": blocks}]
    out = [{"id": "base", "baseline": True, "probabilities": True, "scenarios": [], "blocks": []}]
    for s in scen:
        if split == "scenario":
            out.append({"id": s, "baseline": False, "probabilities": False, "scenarios": [s], "blocks": blocks})
        else:
            out += [{"id": f"{s}.{b}", "baseline": False, "probabilities": False, "scenarios": [s], "blocks": [b]}
                    for b in blocks]
    return out


def asked(spec, call):
    """{component id: [(year, scenario)]} for one call, baselines first."""
    out = {}
    if call["baseline"]:
        out.update({c["id"]: [(spec["base_year"], M.BASE)] for c in M.baselines(spec)})
    for c in M.components(spec):
        if c["block"] in call["blocks"] and call["scenarios"]:
            out[c["id"]] = [(y, s) for s in call["scenarios"] for y in spec["years"]]
    return out


def rationales(spec, call):
    """[(rationale id, what it covers)] for one call."""
    out = M.baseline_rationale() if call["baseline"] else []
    for s in call["scenarios"]:
        out += [(g, d) for g, d in M.rationale_groups(spec, s) if g.split(".")[2] in call["blocks"]]
    return out


def n_sets(spec, call, only=None):
    return sum(len(p) for cid, p in asked(spec, call).items() if only is None or cid in only)


# ── the 2025 record offered in the prompt ────────────────────────────────────

def load_baselines(path=None):
    """data/model/baselines.csv -> {id: {value, source, vintage}}; {} when it is not there yet.
    Ids are baseline component ids (base.N0.construction) or official totals (official.nominal_gdp)."""
    path = path or config.MODEL_BASELINES
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return {r["id"]: {"value": float(r["value"]), "source": r.get("source") or "", "vintage": r.get("vintage") or ""}
                    for r in csv.DictReader(f)}
    except FileNotFoundError:
        return {}


# ── the prompt ───────────────────────────────────────────────────────────────

def _generic(text):
    return (text.replace("{industry}", "the industry").replace("{occupation}", "the occupation group")
            .replace("{year}", "the year"))


def _ids(template, spec):
    per = template["per"]
    return {"industry": f"{template['symbol']}.<industry id>", "occupation": f"{template['symbol']}.<occupation id>",
            "cell": f"{template['symbol']}.<industry id>.<occupation id>", "scalar": template["symbol"]}[per]


def _g(v):
    return f"{v:,.6g}" if abs(v) < 1e6 else f"{v:,.0f}"


def build_prompt(spec, call, record, today, only=None):
    """-> (prompt, allowed question ids). `only`: ask for just these component ids (a retry)."""
    want = {cid: p for cid, p in asked(spec, call).items() if only is None or cid in only}
    why = [(g, d) for g, d in rationales(spec, call) if only is None or g in only]
    scen = call["scenarios"]
    out = [f"Today is {today.isoformat()}.", "",
           "This is a model of the US economy built from accounting identities over 22 industries and 22 "
           "occupation groups. You forecast its components; every top-line outcome (real GDP growth, "
           "unemployment, labor force participation, productivity, the labor share, real pay) is then computed "
           "from your components, not asked directly. "
           + (f"You are asked for {n_sets(spec, call, only=set(want))} sets of five quantiles in all. Answer every one." if want
              else "")]
    if only is not None:
        out += ["", "This call completes an earlier answer: only the components listed below are still needed."]
    out += ["", "===== AI SCENARIOS =====", "", spec["scenarios"]["preamble"], ""]
    for s in spec["scenarios"]["items"]:
        out += [f"--- {s['id']}: {s['label']} ---"] + [f"{i['name']}: {i['text']}" for i in s["indicators"]] + [""]
    if spec["scenarios"].get("footnote"):
        out += [f"Note on Level-5 autonomy: {spec['scenarios']['footnote']}", ""]

    out += ["===== HOW TO ANSWER =====", "",
            "Each component is answered with five quantiles: the 5th, 25th, 50th, 75th and 95th percentiles of "
            "your belief (q05, q25, q50, q75, q95), strictly increasing, in the component's unit. "
            "A share is a number between 0 and 1, never 0 or 1 exactly; a percentage is a number of percent.",
            ""]
    if scen:
        out += [f"Every future component is asked for each of the years {', '.join(spec['years'])}, and for each "
                f"scenario ({', '.join(scen)}): your forecast assuming that scenario is the one that occurs. "
                "All values are annual: annual totals for output and hours, annual averages of monthly or quarterly "
                "figures for the labor market and wages. An index is relative to the 2025 annual value (1.10 means "
                "10% above 2025).", ""]
    out += ["Industries follow BEA's sector-level industries. Every government employee counts in federal or in "
            "state and local government, whatever the work: a public school teacher is in state and local "
            "government, not educational services. Employment and hours are for civilians only.", "",
            "Industry ids: " + "; ".join(f"{i['id']} ({i['name']}, NAICS {i['naics']})" for i in spec["industries"]) + ".", "",
            "Occupation ids (SOC major groups, military excluded): "
            + "; ".join(f"{o['id']} ({o['name']}, SOC {o['soc']})" for o in spec["occupations"]) + ".", ""]

    if call["probabilities"]:
        out += ["===== SCENARIO PROBABILITIES =====", "",
                f"Give the probability, in percent, that each scenario ({', '.join(M.scenario_ids(spec))}) is the "
                "one that best describes AI capability at the end of 2030, summing to 100. These go in "
                "submit_forecast as scenario_probabilities.", ""]

    every = M.by_id(spec)
    if call["baseline"] and any(c.startswith("base.") for c in want):
        out += ["===== 2025 BASELINES =====", "",
                "Each is asked once, for 2025, under scenario \"base\": forecasts {\"2025\": {\"base\": {q05..q95}}}. "
                "Where an official 2025 figure is published it is given; your quantiles are about the final "
                "annual value.", ""]
        for t in spec["baselines"]:
            ids = [cid for cid in want if cid.startswith(f"base.{t['symbol']}.") or cid == f"base.{t['symbol']}"]
            if not ids:
                continue
            out += [f"--- base.{_ids(t, spec)}: {t['name']} ---", _generic(t["text"]), f"Unit: {t['unit']}."]
            given = [f"{cid}: {_g(record[cid]['value'])}" for cid in ids if cid in record]
            out += (["Official data (" + (record[ids[0]]["source"] if ids[0] in record else "see sources") + "):"] + given
                    if given else ["Official data: not offered."])
            if only is not None:
                out += ["Still needed: " + ", ".join(ids)]
            out += [""]
        totals = [f"{k.removeprefix('official.')}: {_g(v['value'])} ({v['source']})" for k, v in record.items()
                  if k.startswith("official.")]
        if totals:
            out += ["Official 2025 totals, for reference: " + "; ".join(totals) + ".", ""]

    for b in spec["blocks"]:
        temps = [t for t in spec["components"] if t["block"] == b["id"]]
        ids_b = [cid for cid in want if not cid.startswith("base.") and every[cid]["block"] == b["id"]]
        if not ids_b:
            continue
        out += [f"===== {b['name'].upper()} =====", ""]
        for t in temps:
            ids = [cid for cid in ids_b if cid.split(".")[0] == t["symbol"]]
            if not ids:
                continue
            out += [f"--- {_ids(t, spec)}: {t['name']} ---", _generic(t["text"]), f"Unit: {t['unit']}. Resolves on: {t['source']}."]
            if only is not None:
                out += ["Still needed: " + ", ".join(ids)]
            out += [""]
        if b["id"] == "mix":
            out += ["The occupation shares of one industry should sum to about 1; they are rescaled to sum to 1 exactly.", ""]
        if b["id"] == "automation":
            out += ["The share done by a human alone is 1 minus the two shares; if the two shares sum above 1 they are "
                    "scaled down to sum to 1.", ""]

    if why:
        out += ["===== RATIONALES =====", "",
                "Give a short rationale (a few sentences) for each group below, as a cell {question_id, rationale} "
                "in submit_cells: what drives your forecasts for that group, and the sources that informed them.",
                "Ids: " + ", ".join(g for g, _ in why), ""]

    out += ["===== DELIVERY =====", "",
            "Deliver with submit_cells, in as many calls as you like: any subset of the components per call, each "
            "with every year and scenario it asks for; a later cell for a component replaces the earlier one. "
            "submit_cells replies with what is still missing. Deliver block by block in the order above. "
            "Then call submit_forecast ONCE"
            + (", with the scenario probabilities" if call["probabilities"] else "")
            + ", a short overall rationale, the key sources you used, and any cells not yet delivered."]
    return "\n".join(out), list(want) + [g for g, _ in why]


# ── the answer tools ─────────────────────────────────────────────────────────

def cell_schema(spec):
    q = {"type": "object", "properties": {k: {"type": "number"} for k in spec["quantiles"]},
         "required": list(spec["quantiles"])}
    return {"type": "object",
            "properties": {
                "question_id": {"type": "string",
                                "description": "a component id (Q.construction, sigma.retail.sales, base.N0.mining) or a rationale id (why....)"},
                "forecasts": {"type": "object", "description": "by year, then scenario (or \"base\" for a 2025 baseline), then q05..q95",
                              "additionalProperties": {"type": "object", "additionalProperties": q}},
                "rationale": {"type": "string", "description": "for a rationale id only"}},
            "required": ["question_id"]}


def tools(spec, call):
    cells = {"type": "array", "items": cell_schema(spec)}
    submit_cells = {
        "description": "Deliver forecasts in pieces: any subset of the components (and rationales), each with every "
                       "year and scenario it asks for. Call it as often as you like; a later cell for a component "
                       "replaces the earlier one. Returns how many have been received and which are still missing.",
        "parameters": {"type": "object", "properties": {"forecasts": cells}, "required": ["forecasts"]}}
    props = {"rationale": {"type": "string"}, "key_sources": {"type": "array", "items": {"type": "string"}},
             "forecasts": cells}
    required = ["rationale"]
    if call["probabilities"]:
        props["scenario_probabilities"] = {
            "type": "object", "description": "percent for each scenario, summing to 100",
            "properties": {s: {"type": "number", "minimum": 0, "maximum": 100} for s in M.scenario_ids(spec)},
            "required": M.scenario_ids(spec)}
        required.insert(0, "scenario_probabilities")
    submit_forecast = {
        "description": "Submit your final answer: " + ("the scenario probabilities, " if call["probabilities"] else "")
                       + "a short rationale, the key sources you read, and any cells not yet delivered with submit_cells.",
        "parameters": {"type": "object", "properties": props, "required": required}}
    return submit_cells, submit_forecast


# ── cleaning ─────────────────────────────────────────────────────────────────

def _number(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def clean_cell(spec, component, raw, pairs):
    """A component's raw answer -> (forecasts {year: {scenario: {q..}}}, problems). Keeps exactly the
    (year, scenario) pairs asked; a set with a value missing, not a number, outside the component's bounds,
    or not strictly increasing is left out and named in `problems`, never repaired."""
    given = raw.get("forecasts") if isinstance(raw, dict) else None
    given = given if isinstance(given, dict) else {}
    out, problems = {}, []
    for y, s in pairs:
        by_s = given.get(y) if isinstance(given.get(y), dict) else {}
        cell = by_s.get(s) if isinstance(by_s.get(s), dict) else None
        if cell is None:
            problems.append(f"{y}/{s}: missing")
            continue
        vals = [_number(cell.get(k)) for k in spec["quantiles"]]
        if any(v is None for v in vals):
            problems.append(f"{y}/{s}: a quantile is missing or not a number")
        elif not all(M.bounds_ok(component, v) for v in vals):
            problems.append(f"{y}/{s}: outside the bounds of {component['unit']}: {vals}")
        elif any(b <= a for a, b in zip(vals, vals[1:])):
            problems.append(f"{y}/{s}: quantiles not strictly increasing {vals}")
        else:
            out.setdefault(y, {})[s] = dict(zip(spec["quantiles"], vals))
    return out, problems


def clean_probabilities(spec, answer):
    """-> (probabilities or None, problems). Kept as given when within one point of 100."""
    raw = (answer or {}).get("scenario_probabilities")
    vals = {s: _number((raw or {}).get(s)) if isinstance(raw, dict) else None for s in M.scenario_ids(spec)}
    if any(v is None or not 0 <= v <= 100 for v in vals.values()):
        return None, ["scenario_probabilities: missing or out of range"]
    if abs(sum(vals.values()) - 100) > 1:
        return None, [f"scenario_probabilities: sum to {sum(vals.values()):g}, not 100"]
    return vals, []


def estimate(spec, call, prompt):
    """Rough token counts for one call: the prompt (input, before research) and the answer (output)."""
    return {"prompt_chars": len(prompt), "input_tokens": len(prompt) // 4,
            "output_tokens": n_sets(spec, call) * TOKENS_PER_SET + len(rationales(spec, call)) * 120}
