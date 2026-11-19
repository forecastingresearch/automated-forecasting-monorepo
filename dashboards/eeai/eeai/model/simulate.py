"""A run file -> simulated worlds -> summaries the page draws (results/model/sims/<run_id>.json).

    python3 -m eeai model simulate RUN_FILE [--worlds N] [--out DIR] [--seed S]

Needs numpy (pip install -e 'dashboards/eeai[model]'). For each model in the
run and each scenario: fit every quantile set (metalog.Fit), draw `worlds`
independent worlds, apply the identities (identities.compute). The
unconditional forecast mixes a model's scenario worlds by its own scenario
probabilities; the ensemble mixes the models' worlds with equal weight. Each
outcome is summarized, per year, as its 5th, 25th, 50th, 75th and 95th
percentiles across worlds: the median and the 50% and 90% intervals.

Draws are independent across components and years, as the design note's v0
agrees, so the intervals understate uncertainty; the page says so.
"""
import json
import math
import sys
from pathlib import Path

from .. import config
from . import instrument as I
from . import spec as M

PCTS = (5, 25, 50, 75, 95)
TRANSFORM_CODE = {"none": 0, "log": 1, "logit": 2}
SHAPE = {"industry": ("I",), "occupation": ("O",), "cell": ("I", "O"), "scalar": ()}
# The identities' vector outcomes and what their last axis is.
PER_INDUSTRY = ("sector_growth", "sector_contribution", "sector_share")
PER_OCCUPATION = ("occupation_employment", "occupation_unemployment", "occupation_premium", "occupation_time",
                  "occupation_demand")


def load_run(path):
    """-> (rows, {model label: rows}), the models in panel order (rows land in the order calls finish)."""
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").split("\n") if line.strip()]
    by = {}
    for r in rows:
        by.setdefault(r["label"], []).append(r)
    panel = next((r.get("panel") for r in rows if r.get("panel")), None) or {}
    order = [m.get("label") for m in panel.get("members") or []]
    rank = {label: (order.index(label) if label in order else len(order), label) for label in by}
    return rows, dict(sorted(by.items(), key=lambda kv: rank[kv[0]]))


def _layout(spec, np):
    """Index arrays that turn a flat row of draws into the identities' arrays.
    -> (base items, base layout, future items, future layout); an item is (component, year, scenario-free)."""
    nI, nO = len(spec["industries"]), len(spec["occupations"])
    dims = {"I": nI, "O": nO}
    base_items, base_lay = [], {}
    for t in spec["baselines"]:
        shape = tuple(dims[d] for d in SHAPE[t["per"]])
        ids = [c["id"] for c in M._expand(spec, t)]
        start = len(base_items)
        base_items += ["base." + i for i in ids]
        base_lay[t["symbol"]] = np.arange(start, start + len(ids)).reshape(shape) if shape else np.array(start)
    fut_items, fut_lay = [], {}
    T = len(spec["years"])
    for t in spec["components"]:
        shape = tuple(dims[d] for d in SHAPE[t["per"]])
        ids = [c["id"] for c in M._expand(spec, t)]
        start = len(fut_items)
        fut_items += [(i, y) for y in spec["years"] for i in ids]
        fut_lay[t["symbol"]] = np.arange(start, start + T * len(ids)).reshape((T,) + shape)
    return base_items, base_lay, fut_items, fut_lay


def _quantiles(spec, rows_by_id, cid, year, scenario):
    cell = ((rows_by_id.get(cid) or {}).get("forecasts") or {}).get(year, {}).get(scenario)
    return [cell[k] for k in spec["quantiles"]] if cell else None


def summarize(np, arr, decimals=5):
    """(worlds, years[, k]) -> [[q05..q95] per year] (or per k, then per year); NaN -> None
    (a growth rate's 2025, which has no year before it)."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)     # the all-NaN 2025 column of a growth rate
        q = np.nanpercentile(arr, PCTS, axis=0)
    q = np.moveaxis(q, 0, -1)                                     # (years[, k], 5)
    if q.ndim == 3:
        q = np.swapaxes(q, 0, 1)                                  # (k, years, 5)

    def clean(x):
        return None if not math.isfinite(x) else float(f"{x:.{decimals}g}")
    return [[clean(x) for x in row] for row in q] if q.ndim == 2 else [[[clean(x) for x in row] for row in k] for k in q]


def simulate_system(spec, rows, worlds, rng, np, chunk=2000):
    """One model's rows -> ({scenario: outcomes (worlds, ...) float32}, diagnostics). Raises ValueError if incomplete."""
    from . import identities, metalog
    by_id = {r["question_id"]: r for r in rows}
    every = M.by_id(spec)
    base_items, base_lay, fut_items, fut_lay = _layout(spec, np)
    qb = [_quantiles(spec, by_id, cid, spec["base_year"], M.BASE) for cid in base_items]
    missing = [cid for cid, q in zip(base_items, qb) if q is None]
    if missing:
        raise ValueError(f"{len(missing)} baselines missing, e.g. {missing[:3]}")
    tb = [TRANSFORM_CODE[every[cid]["transform"]] for cid in base_items]
    gaps = [int(y) - int(p) for p, y in zip([spec["base_year"]] + spec["years"][:-1], spec["years"])]
    out, diag = {}, {"fallback_rate": {}, "share_sum": {}, "automation_rescaled": {}}
    base_med = {s: np.asarray(qb)[:, 2][idx][None] for s, idx in base_lay.items()}
    diag["baseline_totals"] = {k: float(v[0]) for k, v in identities.baseline_totals(base_med).items()}
    for scen in M.scenario_ids(spec):
        qf = [_quantiles(spec, by_id, cid, y, scen) for cid, y in fut_items]
        missing = [f"{cid}/{y}" for (cid, y), q in zip(fut_items, qf) if q is None]
        if missing:
            raise ValueError(f"{scen}: {len(missing)} quantile sets missing, e.g. {missing[:3]}")
        tf = [TRANSFORM_CODE[every[cid]["transform"]] for cid, _ in fut_items]
        fit = metalog.Fit(np.asarray(qb + qf), np.asarray(tb + tf), spec["probs"])
        diag["fallback_rate"][scen] = round(fit.fallback_rate, 5)
        parts, sums, over = [], [], []
        nb = len(base_items)
        for start in range(0, worlds, chunk):
            w = min(chunk, worlds - start)
            d = fit.draw(rng, w)
            base = {s: d[:, idx] if idx.ndim else d[:, int(idx)] for s, idx in base_lay.items()}
            fut = {s: d[:, nb + idx] for s, idx in fut_lay.items()}
            res, counts = identities.compute(base, fut, gaps)
            parts.append({k: v.astype(np.float32) for k, v in res.items()})
            sums.append(counts["share_sum"].mean())
            over.append(counts["automation_rescaled"].mean())
        out[scen] = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
        diag["share_sum"][scen] = round(float(np.mean(sums)), 4)
        diag["automation_rescaled"][scen] = round(float(np.mean(over)), 5)
        # The direct forecasts against the computed ones: medians, per year.
        checks = {}
        for t in spec["components"]:
            if t.get("cross_check"):
                direct = [(_quantiles(spec, by_id, t["symbol"], y, scen) or [None] * 5)[2] for y in spec["years"]]
                computed = np.nanmedian(out[scen][t["cross_check"]][:, 1:], axis=0)
                checks[t["cross_check"]] = {"direct": direct, "computed": [round(float(x), 3) for x in computed]}
        diag.setdefault("cross_checks", {})[scen] = checks
    return out, diag


def run(path, worlds=10000, seed=20261118, record=None):
    """-> the summary blob for one run file."""
    import numpy as np
    spec = M.load()
    rows, by = load_run(path)
    rng = np.random.default_rng(seed)
    scen = M.scenario_ids(spec)
    record = record if record is not None else I.load_baselines()
    if not record and any(r.get("synthetic") for r in rows):
        from . import synthetic
        record = synthetic.placeholder_record(spec)
    official = {k.removeprefix("official."): v["value"] for k, v in record.items() if k.startswith("official.")}
    blob = {"run_id": Path(path).stem, "run_date": rows[0]["run_date"], "instrument": rows[0]["instrument"],
            "synthetic": any(r.get("synthetic") for r in rows), "seed": seed, "worlds": worlds,
            "years": [spec["base_year"]] + spec["years"], "systems": [], "skipped": {}, "probabilities": {},
            "summaries": {}, "diagnostics": {}, "official": official}
    keep = {s: [] for s in scen}
    keep_unc = []
    systems = {}
    for label, rs in by.items():
        call = next((r["call"] for r in rs if r.get("call")), {}) or {}
        probs = call.get("scenario_probabilities")
        try:
            out, diag = simulate_system(spec, rs, worlds, rng, np)
        except ValueError as exc:
            blob["skipped"][label] = str(exc)
            continue
        diag["problems"] = sum(1 for r in rs if r.get("problems"))
        diag["baseline_check"] = {k: {"computed": round(v, 3), "official": official.get(k),
                                      "diff": round(v - official[k], 3) if k in official else None}
                                  for k, v in diag.pop("baseline_totals").items()}
        systems[label] = (out, probs)
        blob["systems"].append(label)
        blob["probabilities"][label] = probs
        blob["diagnostics"][label] = diag
    k = max(len(systems), 1)
    for label, (out, probs) in systems.items():
        summ = {s: {name: summarize(np, arr) for name, arr in out[s].items()} for s in scen}
        if probs:
            take = {s: int(round(worlds * probs[s] / 100)) for s in scen}
            unc = {name: np.concatenate([out[s][name][:take[s]] for s in scen]) for name in out[scen[0]]}
            summ[M.UNCONDITIONAL] = {name: summarize(np, arr) for name, arr in unc.items()}
            perm = rng.permutation(len(unc["gdp_growth"]))[: worlds // k]
            keep_unc.append({name: arr[perm] for name, arr in unc.items()})
        for s in scen:
            keep[s].append({name: arr[: worlds // k] for name, arr in out[s].items()})
        blob["summaries"][label] = summ
    if systems:
        ens = {s: {name: summarize(np, np.concatenate([p[name] for p in keep[s]])) for name in keep[s][0]} for s in scen}
        if keep_unc:
            ens[M.UNCONDITIONAL] = {name: summarize(np, np.concatenate([p[name] for p in keep_unc])) for name in keep_unc[0]}
        blob["summaries"]["ensemble"] = ens
        mean_probs = [p for _, p in systems.values() if p]
        if mean_probs:
            blob["probabilities"]["ensemble"] = {s: round(sum(p[s] for p in mean_probs) / len(mean_probs), 2) for s in scen}
    return blob


def main(args):
    try:
        import numpy
    except ImportError:
        sys.exit("simulate needs numpy: pip install -e 'dashboards/eeai[model]'")
    blob = run(args.run_file, worlds=args.worlds, seed=args.seed)
    out = Path(args.out or config.MODEL_SIMS)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{blob['run_id']}.json"
    path.write_text(json.dumps(blob, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{path}: {len(blob['systems'])} model(s), {blob['worlds']} worlds per scenario"
          + (f"; skipped {', '.join(blob['skipped'])}" if blob["skipped"] else "")
          + (" -- SYNTHETIC" if blob["synthetic"] else ""))
    return 0
