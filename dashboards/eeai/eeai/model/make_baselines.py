"""The 2025 record offered in the prompt: data/model/baselines.csv.

    python3 -m eeai model baselines --template   # write data/model/source/published_2025.csv to fill in
    python3 -m eeai model baselines              # CPS extract + published figures -> data/model/baselines.csv

Two inputs, both downloaded by hand into data/model/source/ (not tracked):

1. cps_2025.csv: an IPUMS CPS extract (cps.ipums.org), the twelve basic
   monthly samples of 2025, as CSV, with YEAR, MONTH, WTFINL, AGE, EMPSTAT,
   CLASSWKR, IND, OCC, AHRSWORKT. From it, with the design note's rules:
   employment, hours actually worked and the occupation mix by industry
   (every government employee in federal or state and local government, by
   CLASSWKR; civilians only), unemployment by occupation of last job, the
   unemployed with no occupation, and the population 16 and over. Annual
   averages are the mean of the months present.
2. published_2025.csv: id,value,source,vintage for what BEA and BLS publish:
   nominal value added and the labor share by industry (BEA GDP by
   Industry), median weekly earnings by occupation (CPS table 39), the
   earnings deciles (Usual Weekly Earnings table 5), and the official totals
   the identities are checked against (official.nominal_gdp, .employment,
   .unemployment_rate, .lfpr). --template writes it with every id and a blank
   value. A published value replaces the CPS tabulation's for the same id.

Only these aggregates are written; no microdata goes into git. The automation
baselines (sA0, sM0, rA0, rM0) have no official source and are not offered.

The industry and occupation code ranges below are the Census 2017 industry
and 2018 occupation codes as IPUMS reports them in IND and OCC for 2025;
check them against the Census code lists before relying on the result.
"""
import csv
import sys
from pathlib import Path

from .. import config
from . import spec as M

# Census 2017 industry code (IPUMS IND) -> the model's industry. Government
# employees are assigned by CLASSWKR first, whatever their IND.
IND_RANGES = [
    (170, 290, "agriculture"), (370, 490, "mining"), (570, 690, "utilities"), (770, 770, "construction"),
    (1070, 2390, "nondurable"), (2470, 3990, "durable"),            # 321 (wood) and 327 (nonmetallic minerals) fall in 2470-3990
    (4070, 4590, "wholesale"), (4670, 5790, "retail"), (6070, 6390, "transportation"), (6470, 6780, "information"),
    (6870, 6992, "finance"), (7071, 7190, "real_estate"), (7270, 7490, "professional"), (7570, 7570, "management"),
    (7580, 7790, "administrative"), (7860, 7890, "education"), (7970, 8470, "health"), (8561, 8590, "arts"),
    (8660, 8690, "accommodation"), (8770, 9290, "other_services"),
    # Public administration (9370-9590) not caught by CLASSWKR: the level of government is unknown; state and local.
    (9370, 9590, "state_local"),
]
MILITARY_IND = (9670, 9870)
# Census 2018 occupation code (IPUMS OCC) -> SOC major group.
OCC_RANGES = [
    (10, 440, "management"), (500, 960, "business"), (1005, 1240, "computer"), (1305, 1560, "engineering"),
    (1600, 1980, "science"), (2001, 2060, "community"), (2100, 2180, "legal"), (2205, 2555, "education"),
    (2600, 2970, "arts"), (3000, 3550, "practitioners"), (3601, 3655, "healthcare_support"), (3700, 3960, "protective"),
    (4000, 4160, "food"), (4200, 4255, "grounds"), (4330, 4655, "personal_care"), (4700, 4965, "sales"),
    (5000, 5940, "office"), (6005, 6130, "farming"), (6200, 6950, "construction"), (7000, 7640, "repair"),
    (7700, 8990, "production"), (9005, 9760, "transport"),
]
MILITARY_OCC = (9800, 9830)
FEDERAL, STATE_LOCAL = {25}, {27, 28}          # IPUMS CLASSWKR
EMPLOYED, UNEMPLOYED, ARMED = {10, 12}, {20, 21, 22}, {1}
NIU_HOURS = {999}
SOURCE = "CPS 2025 basic monthly (IPUMS), tabulated by FRI (eeai/model/make_baselines.py)"


def _lookup(code, ranges):
    return next((name for lo, hi, name in ranges if lo <= code <= hi), None)


def industry_of(row):
    cls, ind = int(row["CLASSWKR"] or 0), int(row["IND"] or 0)
    if cls in FEDERAL:
        return "federal"
    if cls in STATE_LOCAL:
        return "state_local"
    if MILITARY_IND[0] <= ind <= MILITARY_IND[1]:
        return None
    return _lookup(ind, IND_RANGES)


def occupation_of(row):
    occ = int(row["OCC"] or 0)
    return None if MILITARY_OCC[0] <= occ <= MILITARY_OCC[1] else _lookup(occ, OCC_RANGES)


def tabulate(rows, spec):
    """IPUMS rows -> {baseline id: value}: E0, H0, sigma0, u0, n0, Pop0, plus counts for the record."""
    months, pop, E, H, cell, U_o, U_none = set(), 0.0, {}, {}, {}, {}, 0.0
    skipped = 0
    for r in rows:
        if int(r["AGE"] or 0) < 16:
            continue
        status, w = int(r["EMPSTAT"] or 0), float(r["WTFINL"] or 0)
        if status in ARMED or not w:
            continue
        months.add((r["YEAR"], r["MONTH"]))
        pop += w
        if status in EMPLOYED:
            ind, occ = industry_of(r), occupation_of(r)
            if ind is None or occ is None:
                skipped += 1
                continue
            hrs = int(r["AHRSWORKT"] or 0)
            E[ind] = E.get(ind, 0) + w
            H[ind] = H.get(ind, 0) + w * (0 if hrs in NIU_HOURS else hrs) * 52
            cell[(ind, occ)] = cell.get((ind, occ), 0) + w
        elif status in UNEMPLOYED:
            occ = occupation_of(r) if int(r["OCC"] or 0) else None
            if occ is None:
                U_none += w
            else:
                U_o[occ] = U_o.get(occ, 0) + w
    k = len(months) or 1
    out = {}
    E_o = {}
    for i in spec["industries"]:
        e = E.get(i["id"], 0) / k
        out[f"base.E0.{i['id']}"] = e / 1e6
        out[f"base.H0.{i['id']}"] = H.get(i["id"], 0) / k / 1e6
        for o in spec["occupations"]:
            c = cell.get((i["id"], o["id"]), 0) / k
            out[f"base.sigma0.{i['id']}.{o['id']}"] = c / e if e else 0.0
            E_o[o["id"]] = E_o.get(o["id"], 0) + c
    for o in spec["occupations"]:
        u = U_o.get(o["id"], 0) / k
        out[f"base.u0.{o['id']}"] = u / (u + E_o[o["id"]]) if u + E_o[o["id"]] else 0.0
    labor_force = sum(E_o.values()) + (sum(U_o.values()) + U_none) / k
    out["base.n0"] = U_none / k / labor_force if labor_force else 0.0
    out["base.Pop0"] = pop / k / 1e6
    return out, {"months": k, "employed_skipped": skipped}


def template_rows(spec):
    rows = [(f"base.N0.{i['id']}", "BEA GDP by Industry, value added, 2025, US$ billions") for i in spec["industries"]]
    rows += [(f"base.lambda0.{i['id']}", "BEA GDP by Industry, compensation of employees / value added, 2025") for i in spec["industries"]]
    rows += [(f"base.omega0.{o['id']}", "BLS CPS annual table 39, median weekly earnings, 2025") for o in spec["occupations"]]
    rows += [(f"base.{p}_0", "BLS Usual Weekly Earnings table 5, mean of 2025's four quarters") for p in ("p10", "p50", "p90")]
    rows += [("base.ECI0", "1 by definition (2025 = 1)"), ("base.C0", "1 by definition (2025 = 1)"),
             ("official.nominal_gdp", "BEA, nominal GDP 2025, US$ billions (FRED: GDPA)"),
             ("official.employment", "BLS CPS, employed 2025 annual average, millions (FRED: CE16OV)"),
             ("official.unemployment_rate", "BLS CPS, unemployment rate 2025 annual average, % (FRED: UNRATE)"),
             ("official.lfpr", "BLS CPS, participation rate 2025 annual average, % (FRED: CIVPART)")]
    return rows


def main(args):
    spec = M.load()
    src = config.MODEL_SOURCE
    published = Path(args.published or src / "published_2025.csv")
    if args.template:
        published.parent.mkdir(parents=True, exist_ok=True)
        if published.exists():
            sys.exit(f"{published} exists; not overwriting it")
        with open(published, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "value", "source", "vintage"])
            w.writerows([[i, "1" if i in ("base.ECI0", "base.C0") else "", s, ""] for i, s in template_rows(spec)])
        print(f"{published}: {len(template_rows(spec))} ids to fill in")
        return 0
    cps = Path(args.cps or src / "cps_2025.csv")
    if not cps.exists():
        sys.exit(f"no {cps}: download the IPUMS CPS extract (see eeai/model/make_baselines.py) into {src}/")
    with open(cps, encoding="utf-8", newline="") as f:
        values, info = tabulate(csv.DictReader(f), spec)
    record = {k: (v, SOURCE, f"{info['months']} months") for k, v in values.items()}
    if published.exists():
        with open(published, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if (r.get("value") or "").strip():
                    record[r["id"]] = (float(r["value"]), r.get("source") or "", r.get("vintage") or "")
    else:
        print(f"warning: no {published}; only the CPS tabulation is written (--template makes one)")
    out = Path(args.out or config.MODEL_BASELINES)
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["id", "value", "source", "vintage"])
        for k, (v, s, vin) in record.items():
            w.writerow([k, f"{v:.8g}", s, vin])
    missing = [c["id"] for c in M.baselines(spec) if c["id"] not in record and c["symbol"] not in ("sA0", "sM0", "rA0", "rM0")]
    print(f"{out}: {len(record)} values from {info['months']} months of CPS ({info['employed_skipped']} employed rows "
          f"without a mapped industry or occupation)" + (f"; not offered: {len(missing)}, e.g. {missing[:3]}" if missing else ""))
    return 0
