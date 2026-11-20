"""The simulation summaries -> the model page's data (window.__EEAI_MODEL__) and model.html.

Pure: reads results/model/sims/*.json (simulate.py writes them) and the
definition, calls nothing, needs no numpy. The page shows the latest summary;
the list of runs is there for the record.
"""
import json
from pathlib import Path

from .. import config
from . import spec as M

# What the page draws: id (as identities.compute names it), label, unit,
# decimals, and the kind -- "growth" (an annual rate, none for 2025) or "level".
HEADLINE = [
    ("gdp_growth", "Real GDP growth", "% per year", 1, "growth"),
    ("unemployment_rate", "Unemployment rate", "%", 1, "level"),
    ("lfpr", "Labor force participation rate", "%", 1, "level"),
    ("epop", "Employment-to-population ratio", "%", 1, "level"),
    ("lp_growth", "Labor productivity growth", "% per year", 1, "growth"),
    ("tfp_growth", "TFP growth", "% per year", 1, "growth"),
    ("labor_share", "Labor share of income", "%", 1, "level"),
    ("real_pay_growth", "Real pay per hour, growth", "% per year", 1, "growth"),
    ("real_median_earnings", "Real median weekly earnings", "US$ per week, 2025 prices", 0, "level"),
    ("ratio_90_10", "90/10 earnings ratio", "ratio", 2, "level"),
    ("inflation_pce", "Consumer price inflation (PCE)", "% per year", 1, "growth"),
    ("employment", "Employment", "millions", 1, "level"),
]
DECOMPOSITION = [("real_pay_index", "Real pay per hour"), ("real_pay_lp", "Labor productivity"),
                 ("real_pay_labor_share", "Labor share, relative to 2025"), ("real_pay_price_gap", "Price gap (GDP prices / consumer prices)")]
SECTOR = [("sector_growth", "Real value added growth", "% per year", 1), ("sector_contribution", "Contribution to GDP growth", "pp", 2),
          ("sector_share", "Share of nominal GDP", "%", 1)]
OCCUPATION = [("occupation_employment", "Employment", "millions", 2),
              ("occupation_employment_change", "Employment change since 2025", "%", 1),
              ("occupation_unemployment", "Unemployment rate", "%", 1),
              ("occupation_premium", "Pay premium (median earnings / overall median)", "ratio", 2),
              ("occupation_time", "Human time per unit of work, relative to doing it alone", "ratio", 2)]
NAME = "eeai-model-data.zip"
# The detail cards' data, beside the page and fetched when a card first opens:
# every forecast input (the summaries' "in." series) and the intermediate totals
# between the inputs and the outcomes. The page itself stays small.
INPUTS = "model-inputs.json"
INTERMEDIATE = ("gdp_index", "nominal_gdp", "hours", "unemployed", "labor_force", "tfp_index", "pay_per_hour")


def inputs(summary):
    """A simulation summary -> the detail cards' data: {sys: {scenario: {series: cells}}}."""
    return {sys: {sc: {k: v for k, v in by.items() if k.startswith("in.") or k in INTERMEDIATE} for sc, by in per.items()}
            for sys, per in summary["summaries"].items()}


def load_sims(sims_dir=None):
    """[(run_id, summary)] oldest first."""
    return [(p.stem, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(Path(sims_dir or config.MODEL_SIMS).glob("*.json"))]


def build(sims, spec=None):
    spec = spec or M.load()
    scen = [{"id": M.UNCONDITIONAL, "label": "Unconditional"}] + [
        {"id": s["id"], "label": s["label"], "summary": s["indicators"][0]["text"]} for s in spec["scenarios"]["items"]]
    blob = {"instrument": spec["instrument"], "source": spec["source"], "scenarios": scen,
            "years": [spec["base_year"]] + spec["years"],
            "industries": [{"id": i["id"], "name": i["name"]} for i in spec["industries"]],
            "occupations": [{"id": o["id"], "name": o["name"]} for o in spec["occupations"]],
            "headline": [dict(zip(("id", "label", "unit", "decimals", "kind"), h)) for h in HEADLINE],
            "decomposition": [dict(zip(("id", "label"), d)) for d in DECOMPOSITION],
            "sector": [dict(zip(("id", "label", "unit", "decimals"), s)) for s in SECTOR],
            "occupation": [dict(zip(("id", "label", "unit", "decimals"), o)) for o in OCCUPATION],
            "runs": [{"run_id": r, "date": s["run_date"], "models": s["systems"]} for r, s in sims],
            "latest": None, "synthetic": False, "download": None}
    if sims:
        run_id, s = sims[-1]
        wanted = {h[0] for h in HEADLINE} | {d[0] for d in DECOMPOSITION} | {x[0] for x in SECTOR} | {x[0] for x in OCCUPATION} | {"work_absorbed"}
        blob["latest"] = {"run_id": run_id, "date": s["run_date"], "models": s["systems"], "skipped": s["skipped"],
                          "worlds": s["worlds"], "seed": s["seed"], "probabilities": s["probabilities"],
                          "summaries": {sys: {sc: {k: v for k, v in by.items() if k in wanted} for sc, by in per.items()}
                                        for sys, per in s["summaries"].items()},
                          "diagnostics": s["diagnostics"], "official": s.get("official") or {}}
        blob["synthetic"] = s["synthetic"]
        blob["download"] = NAME
        blob["inputs"] = INPUTS
    # The History view: the ensemble's headline forecasts in every run, oldest first,
    # each with its own years (an earlier run may have asked for fewer).
    heads = [h[0] for h in HEADLINE]
    blob["history"] = [{"run_id": r, "date": s["run_date"], "years": s["years"],
                        "cells": {sc: {k: by[k] for k in heads if k in by} for sc, by in s["summaries"].get("ensemble", {}).items()}}
                       for r, s in sims if s["summaries"].get("ensemble")]
    return blob


def page(blob):
    from dashboard import page as kit
    return kit.render(config.MODEL_PAGE_DIR, {"EEAI_MODEL": blob})


def write(site_dir, sims_dir=None, runs_dir=None):
    """Write model.html (and, with a summary, its detail-card data and its download) into the site folder. -> the blob."""
    sims = load_sims(sims_dir)
    blob = build(sims)
    site_dir = Path(site_dir)
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "model.html").write_text(page(blob), encoding="utf-8")
    if sims:
        (site_dir / INPUTS).write_text(json.dumps(inputs(sims[-1][1]), ensure_ascii=False, separators=(",", ":")),
                                       encoding="utf-8")
        from . import export
        export.bundle(site_dir / NAME, sims[-1], runs_dir)
    return blob
