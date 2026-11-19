"""The model page's download: one zip beside model.html.

    README.md          what is in here
    quantiles.csv      one line per quantile set a model gave: run, model, component, year, scenario, q05..q95
    probabilities.csv  each model's scenario probabilities
    rationales.csv     each model's rationale per group
    summary.json       the simulation summaries the page draws, with the diagnostics
    components.json    the definition (industries, occupations, components)
    baselines.csv      the 2025 record offered in the prompt, when there is one
    runs/<run>.jsonl   the run file: every row, with each call's prompt, searches and page reads
"""
import json
from pathlib import Path

from dashboard import download

from .. import config

QUANTILE_COLUMNS = ["run_id", "run_date", "model", "model_id", "component", "year", "scenario", "q05", "q25", "q50", "q75", "q95"]
README = """# EEAI economy model (v0): the data

{note}A panel of frontier AI models forecasts the components of an
accounting model of the US economy (22 industries, 22 occupation groups),
each as five quantiles, for three AI progress scenarios. The page's outcomes
are computed from the components by the model's identities in {worlds:,}
simulated worlds per scenario and model, every component drawn independently
(so intervals understate uncertainty). Run {run_id}; models: {models}.
"""


def _rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").split("\n") if line.strip()]


def bundle(out, sim, runs_dir=None):
    run_id, s = sim
    path = Path(runs_dir or config.MODEL_RUNS) / f"{run_id}.jsonl"
    rows = _rows(path) if path.exists() else []
    q, probs, why = [], [], []
    for r in rows:
        for y, by in (r.get("forecasts") or {}).items():
            for scen, v in by.items():
                q.append([r["run_id"], r["run_date"], r["label"], r["model"], r["question_id"], y, scen,
                          *(v[k] for k in ("q05", "q25", "q50", "q75", "q95"))])
        call = r.get("call") or {}
        for scen, p in (call.get("scenario_probabilities") or {}).items():
            probs.append([r["run_id"], r["label"], r["model"], scen, p])
        for g, text in (call.get("rationales") or {}).items():
            why.append([r["run_id"], r["label"], r["model"], g, text])
    note = "PLACEHOLDER DATA: these numbers are made up to show the layout.\n\n" if s.get("synthetic") else ""
    files = [("README.md", README.format(note=note, worlds=s["worlds"], run_id=run_id, models=", ".join(s["systems"]))),
             ("quantiles.csv", download.csv_text(QUANTILE_COLUMNS, q)),
             ("probabilities.csv", download.csv_text(["run_id", "model", "model_id", "scenario", "percent"], probs)),
             ("rationales.csv", download.csv_text(["run_id", "model", "model_id", "group", "rationale"], why)),
             ("summary.json", json.dumps(s, ensure_ascii=False, indent=1)),
             ("components.json", config.MODEL_COMPONENTS)]
    if config.MODEL_BASELINES.exists():
        files.append(("baselines.csv", config.MODEL_BASELINES))
    if path.exists():
        files.append((f"runs/{run_id}.jsonl", path))
    return download.bundle(out, files)
