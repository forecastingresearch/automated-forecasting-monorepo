"""Made-up answers in the harness's shape, so the model's page and tests need no calls.

Not forecasts. Each median follows a fixed trend per scenario from the 2025
record (data/model/baselines.csv, or, until that exists, PLACEHOLDER: a
made-up 2025 economy of roughly the right size), with quantiles a fixed
spread apart on the transformed scale. Rows made this way are stamped
`synthetic`, and the page says so across the top.
"""
import hashlib
import math
import random

from . import spec as M

NOTE = "Synthetic placeholder, not a model's forecast."
Z = (-1.6449, -0.6745, 0.0, 0.6745, 1.6449)

# A made-up 2025 economy: nominal value added (US$ billions) and employment
# (millions) by industry, roughly the US's size and mix; labor shares and
# hours per worker set by hand. Not data.
PLACEHOLDER_INDUSTRY = {
    #                 N0      E0     lambda0  hours/worker
    "agriculture":    (300,   2.2,  0.35, 2050),
    "mining":         (420,   0.7,  0.30, 2150),
    "utilities":      (480,   1.4,  0.30, 2000),
    "construction":   (1320, 12.0,  0.60, 1950),
    "durable":        (1680,  9.5,  0.62, 2000),
    "nondurable":     (1350,  5.5,  0.45, 1990),
    "wholesale":      (1800,  3.5,  0.55, 2000),
    "retail":         (1890, 15.5,  0.55, 1650),
    "transportation": (990,   9.0,  0.62, 1950),
    "information":    (1680,  2.9,  0.40, 1950),
    "finance":        (2250,  7.5,  0.45, 2000),
    "real_estate":    (3750,  3.2,  0.08, 1900),
    "professional":   (2400, 14.0,  0.70, 1950),
    "management":     (570,   0.5,  0.75, 2000),
    "administrative": (960,   7.0,  0.70, 1800),
    "education":      (360,   4.5,  0.80, 1700),
    "health":         (2340, 21.0,  0.75, 1800),
    "arts":           (360,   3.5,  0.55, 1500),
    "accommodation":  (930,  11.0,  0.60, 1450),
    "other_services": (600,   7.5,  0.65, 1750),
    "federal":        (1140,  3.3,  0.85, 2000),
    "state_local":    (2430, 18.5,  0.85, 1850),
}
PLACEHOLDER_OCCUPATION = {
    #                     employment share, unemployment rate, median weekly earnings
    "management":         (0.115, 0.020, 1800), "business": (0.055, 0.025, 1500), "computer": (0.035, 0.030, 1850),
    "engineering":        (0.020, 0.020, 1750), "science": (0.010, 0.025, 1500), "community": (0.017, 0.025, 1050),
    "legal":              (0.012, 0.015, 1700), "education": (0.055, 0.025, 1150), "arts": (0.020, 0.045, 1200),
    "practitioners":      (0.060, 0.015, 1450), "healthcare_support": (0.030, 0.045, 750), "protective": (0.019, 0.035, 1100),
    "food":               (0.050, 0.060, 650), "grounds": (0.035, 0.055, 750), "personal_care": (0.020, 0.050, 750),
    "sales":              (0.090, 0.045, 1000), "office": (0.100, 0.040, 900), "farming": (0.007, 0.080, 700),
    "construction":       (0.050, 0.055, 1050), "repair": (0.030, 0.030, 1100), "production": (0.055, 0.045, 950),
    "transport":          (0.075, 0.055, 850),
}
# Where an occupation group concentrates (multiplies its share there).
TILT = {"agriculture": {"farming": 12}, "mining": {"construction": 6, "transport": 2}, "construction": {"construction": 9},
        "durable": {"production": 6, "engineering": 3}, "nondurable": {"production": 6},
        "wholesale": {"sales": 3, "transport": 2}, "retail": {"sales": 5}, "transportation": {"transport": 6},
        "information": {"computer": 6, "arts": 3}, "finance": {"business": 4, "sales": 2, "office": 2},
        "real_estate": {"sales": 3, "grounds": 2}, "professional": {"computer": 4, "business": 3, "legal": 3, "engineering": 3},
        "management": {"management": 3, "business": 3}, "administrative": {"office": 2, "grounds": 5, "protective": 3},
        "education": {"education": 10}, "health": {"practitioners": 6, "healthcare_support": 6, "community": 2},
        "arts": {"arts": 6, "personal_care": 3}, "accommodation": {"food": 12},
        "other_services": {"repair": 4, "personal_care": 4}, "federal": {"protective": 3, "business": 3, "office": 2},
        "state_local": {"education": 7, "protective": 4, "community": 3}}
PLACEHOLDER_SCALARS = {"base.n0": 0.004, "base.Pop0": 274.0, "base.p10_0": 620, "base.p50_0": 1200, "base.p90_0": 2850,
                       "base.ECI0": 1.0, "base.C0": 1.0}
AUTOMATION_2025 = {"sA0": 0.10, "sM0": 0.02, "rA0": 0.75, "rM0": 0.30}


def placeholder_record(spec):
    """{baseline id: value} for a made-up 2025 economy, and the official totals it implies."""
    rec = {}
    for iid, (N0, E0, lam, hours) in PLACEHOLDER_INDUSTRY.items():
        rec[f"base.N0.{iid}"], rec[f"base.E0.{iid}"], rec[f"base.lambda0.{iid}"] = N0, E0, lam
        rec[f"base.H0.{iid}"] = E0 * hours
        raw = {o: share * TILT.get(iid, {}).get(o, 1) for o, (share, _, _) in PLACEHOLDER_OCCUPATION.items()}
        total = sum(raw.values())
        rec.update({f"base.sigma0.{iid}.{o}": v / total for o, v in raw.items()})
    for o, (_, u, omega) in PLACEHOLDER_OCCUPATION.items():
        rec[f"base.u0.{o}"], rec[f"base.omega0.{o}"] = u, omega
        rec.update({f"base.{k}.{o}": v for k, v in AUTOMATION_2025.items()})
    rec.update(PLACEHOLDER_SCALARS)
    E = sum(v[1] for v in PLACEHOLDER_INDUSTRY.values())
    E_o = {o: sum(rec[f"base.E0.{i}"] * rec[f"base.sigma0.{i}.{o}"] for i in PLACEHOLDER_INDUSTRY) for o in PLACEHOLDER_OCCUPATION}
    U = sum(E_o[o] * rec[f"base.u0.{o}"] / (1 - rec[f"base.u0.{o}"]) for o in E_o)
    L = (E + U) / (1 - rec["base.n0"])
    rec.update({"official.nominal_gdp": sum(v[0] for v in PLACEHOLDER_INDUSTRY.values()), "official.employment": E,
                "official.unemployment_rate": (1 - E / L) * 100, "official.lfpr": L / rec["base.Pop0"] * 100})
    return {k: {"value": v, "source": "PLACEHOLDER (made up, not data)", "vintage": ""} for k, v in rec.items()}


# Annual trend per scenario, by symbol: growth rates for levels and indexes; a target for shares and ratios.
GROWTH = {"Q": {"slow": .018, "moderate": .026, "rapid": .045}, "P": {"slow": .022, "moderate": .020, "rapid": .014},
          "pi": {"slow": .012, "moderate": .020, "rapid": .040}, "K": {"slow": .025, "moderate": .035, "rapid": .060},
          "Pop": {"slow": .005, "moderate": .005, "rapid": .005}, "omega": {"slow": .035, "moderate": .038, "rapid": .045},
          "p10": {"slow": .033, "moderate": .034, "rapid": .030}, "p50": {"slow": .035, "moderate": .038, "rapid": .042},
          "p90": {"slow": .037, "moderate": .042, "rapid": .055}, "ECI": {"slow": .035, "moderate": .037, "rapid": .042},
          "C": {"slow": .022, "moderate": .021, "rapid": .018}, "h": {"slow": -.001, "moderate": -.002, "rapid": -.006}}
TARGET = {"sA": {"slow": .30, "moderate": .50, "rapid": .70}, "sM": {"slow": .05, "moderate": .15, "rapid": .30},
          "rA": {"slow": .70, "moderate": .60, "rapid": .45}, "rM": {"slow": .30, "moderate": .20, "rapid": .12}}
CHECKS = {"x_gdp": {"slow": 1.8, "moderate": 2.6, "rapid": 4.5}, "x_productivity": {"slow": 1.2, "moderate": 2.0, "rapid": 4.0},
          "x_tfp": {"slow": 0.8, "moderate": 1.4, "rapid": 3.0}, "x_unemployment": {"slow": 4.3, "moderate": 4.6, "rapid": 5.8},
          "x_lfpr": {"slow": 62.3, "moderate": 62.0, "rapid": 61.0}}


def _base_value(c, record):
    """The 2025 value a future component starts from."""
    sym, rest = c["symbol"], c["id"].split(".")[1:]
    if sym in ("Q", "P", "pi", "K", "ECI", "C"):          # indexes, 2025 = 1
        return 1.0
    if sym == "h":
        return record[f"base.H0.{rest[0]}"]["value"] / record[f"base.E0.{rest[0]}"]["value"]
    if sym in ("p10", "p50", "p90"):
        return record[f"base.{sym}_0"]["value"]
    name = {"lambda": "lambda0", "sigma": "sigma0", "u": "u0", "n": "n0", "Pop": "Pop0", "omega": "omega0",
            "sA": "sA0", "sM": "sM0", "rA": "rA0", "rM": "rM0"}.get(sym)
    return record[".".join(["base", name] + rest)]["value"] if name else None


def _median(c, record, year, scenario, rng):
    yrs = int(year) - 2025
    sym = c["symbol"]
    if c["id"].startswith("base."):
        return record[c["id"]]["value"]
    if sym in CHECKS:
        return CHECKS[sym][scenario] + rng.uniform(-0.2, 0.2)
    b = _base_value(c, record)
    if sym in GROWTH:
        tilt = 0.02 if scenario == "rapid" and c.get("industry") in ("information", "professional") and sym == "Q" else 0
        return b * (1 + GROWTH[sym][scenario] + tilt + rng.uniform(-0.004, 0.004)) ** yrs
    if sym in TARGET:
        return b + (TARGET[sym][scenario] - b) * (1 - math.exp(-yrs / 8))
    if sym == "lambda":
        return b * (1 - {"slow": 0.0, "moderate": 0.002, "rapid": 0.008}[scenario] * yrs)
    if sym == "u":
        return min(b * (1 + {"slow": 0.02, "moderate": 0.06, "rapid": 0.35}[scenario] * min(yrs, 5) / 5), 0.5)
    return b                                    # sigma, n: as in 2025


def _quantiles(c, median, year):
    yrs = max(int(year) - 2025, 0)
    t = c["transform"]
    sd = {"log": 0.02 + 0.015 * math.sqrt(yrs), "logit": 0.05 + 0.04 * math.sqrt(yrs), "none": 0.3 + 0.2 * math.sqrt(yrs)}[t]
    if t == "log":
        median = max(median, 1e-6)                       # (a zero in the record: no observations)
        return [round(median * math.exp(z * sd), 6) for z in Z]
    if t == "logit":
        median = min(max(median, 1e-4), 1 - 1e-4)        # (a share of 0 or 1 in the record, as an empty CPS cell)
        x = math.log(median / (1 - median))
        return [round(1 / (1 + math.exp(-(x + z * sd))), 7) for z in Z]
    return [round(median + z * sd, 4) for z in Z]


def answer(spec, record, model, keys, today):
    """Cells for `keys` (component and rationale ids) and the final answer.
    A baseline the record lacks (the real record offers no automation
    baselines) comes from the placeholder economy, so made-up answers work with
    the real data/model/baselines.csv too."""
    rng = random.Random(int(hashlib.sha256(f"{model}|{today}".encode()).hexdigest()[:12], 16))
    record = {**placeholder_record(spec), **record}
    every = M.by_id(spec)
    cells = {}
    for k in keys:
        if k.startswith("why."):
            cells[k] = {"question_id": k, "rationale": NOTE}
            continue
        c = every[k]
        forecasts = {}
        for y, s in M.asked(spec, c):
            forecasts.setdefault(y, {})[s] = dict(zip(spec["quantiles"], _quantiles(c, _median(c, record, y, s, rng), y)))
        cells[k] = {"question_id": k, "forecasts": forecasts}
    slow, rapid = round(30 + rng.uniform(-6, 6), 1), round(20 + rng.uniform(-6, 6), 1)
    final = {"scenario_probabilities": {"slow": slow, "moderate": round(100 - slow - rapid, 1), "rapid": rapid},
             "rationale": NOTE, "key_sources": []}
    return cells, final


def harness_run(spec, record, today):
    """A stand-in for fri_forecaster.harness.run that makes no call."""
    def run(*, model, workdir, allowed_keys, **_):
        cells, final = answer(spec, record, model, allowed_keys, today)
        return {"rc": 0, "seconds": 0.0, "evidence": [], "cells": cells, "answer": final,
                "usage": {"turns": 0, "cost_usd": 0.0, "harness": "synthetic"},
                "delivery": {"cells_calls": 1, "cells_in_pieces": len(cells), "cells_in_final": 0},
                "forced": False, "debrief": None, "trace": None, "workdir": workdir}
    return run
