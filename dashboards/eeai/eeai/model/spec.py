"""The economy model's definition (data/model/components.json), expanded.

The file is written by hand and compact: the industries, the occupation
groups, and one template per kind of component. Expanded, every component is
a question like the survey's, with its own id:

    Q.construction          real value added of construction (per industry)
    u.office                unemployment rate, office and administrative support (per occupation)
    sigma.retail.sales      sales workers' share of retail employment (per industry and occupation)
    Pop                     population 16 and over (scalar)
    base.N0.construction    a 2025 baseline

A future component is asked for every scenario and year; a baseline once, for
2025, under BASE. Each answer is five quantiles (QUANTILES).
"""
import json

from .. import config

UNCONDITIONAL = "unconditional"
BASE = "base"           # the scenario key of a 2025 baseline's answer
INDEXING = ("industry", "occupation", "cell", "scalar")


def load(path=None):
    with open(path or config.MODEL_COMPONENTS, encoding="utf-8") as f:
        return json.load(f)


def scenario_ids(spec):
    return [s["id"] for s in spec["scenarios"]["items"]]


def _expand(spec, template):
    """One template -> its components, as (industry, occupation) pairs; None where not indexed by it."""
    ind, occ = spec["industries"], spec["occupations"]
    pairs = {"industry": [(i, None) for i in ind], "occupation": [(None, o) for o in occ],
             "cell": [(i, o) for i in ind for o in occ], "scalar": [(None, None)]}[template["per"]]
    out = []
    for i, o in pairs:
        cid = ".".join([template["symbol"]] + [p["id"] for p in (i, o) if p])
        text = template["text"].replace("{industry}", i["name"].lower() if i else "")
        text = text.replace("{occupation}", f"{o['name'].lower()} occupations" if o else "")
        out.append({**{k: v for k, v in template.items() if k != "text"}, "id": cid, "text": text,
                    "industry": i and i["id"], "occupation": o and o["id"],
                    "resolvable": template.get("resolvable", True)})
    return out


def components(spec):
    """Every future component, in the file's order."""
    return [c for t in spec["components"] for c in _expand(spec, t)]


def baselines(spec):
    """Every 2025 baseline, ids under `base.`."""
    return [dict(c, id="base." + c["id"], block="base") for t in spec["baselines"] for c in _expand(spec, t)]


def by_id(spec):
    return {c["id"]: c for c in components(spec) + baselines(spec)}


def asked(spec, component):
    """The (year, scenario) pairs a component is asked for."""
    if component["id"].startswith("base."):
        return [(spec["base_year"], BASE)]
    return [(y, s) for s in scenario_ids(spec) for y in spec["years"]]


def n_sets(spec, ids=None):
    """Quantile sets asked, over `ids` (default: everything)."""
    every = by_id(spec)
    return sum(len(asked(spec, every[i])) for i in (ids if ids is not None else every))


def rationale_groups(spec, scenario):
    """The rationale asked per scenario: one per industry for output and the
    occupation mix, one per occupation for automation, one per other block.
    -> [(group id, description)]."""
    out = []
    for b in spec["blocks"]:
        if b["rationale_per"] == "industry":
            out += [(f"why.{scenario}.{b['id']}.{i['id']}", f"{b['name']}: {i['name']}") for i in spec["industries"]]
        elif b["rationale_per"] == "occupation":
            out += [(f"why.{scenario}.{b['id']}.{o['id']}", f"{b['name']}: {o['name']}") for o in spec["occupations"]]
        else:
            out.append((f"why.{scenario}.{b['id']}", b["name"]))
    return out


def baseline_rationale():
    return [("why.base", "The 2025 baselines")]


def bounds_ok(component, v):
    """Strictly inside a share's (0, 1) or a positive quantity's (0, hi];
    within [lo, hi] for an untransformed one."""
    lo, hi = component["bounds"]
    if component["transform"] == "logit":
        return 0 < v < 1
    if component["transform"] == "log":
        return 0 < v <= hi
    return lo <= v <= hi
