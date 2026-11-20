"""Compute the EEAI dashboard's public cohort summary from private weighted distributions."""
import csv
import os
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from tempfile import NamedTemporaryFile

from dashboard.download import csv_text
from . import config, survey

SUMMARY = config.DATA / "human_forecasts.csv"
COHORTS = ("superforecaster", "full_panel")
CELL = ("question", "horizon", "condition", "elicited_statistic", "option", "cohort")
FIELDS = (*CELL, "value", "respondents", "extracted_on")
ALIASES = {"whitecollar": "jobs_business_analytical", "bluecollar": "jobs_skilled_trade_industrial",
           "pinkcollar": "jobs_care_service"}


def display_cells():
    """The original survey cells and the precision shown in the forecast charts and details."""
    cells = {}
    for q in survey.load()["questions"]:
        for horizon in q["horizons"]:
            if horizon["added"]:
                continue
            for condition in ("unconditional", "slow", "moderate", "rapid"):
                stats = ("p10", "p50", "p90") if q["uncertainty"] and condition in ("unconditional", "rapid") else ("p50",)
                for stat in stats:
                    for cohort in COHORTS:
                        cells[q["id"], horizon["id"], condition, stat, "", cohort] = q["decimals"]
    for option in ("slow", "moderate", "rapid"):
        for cohort in COHORTS:
            cells["scenario_probabilities", "2030", "unconditional", "probability", option, cohort] = 1
    return cells


def display_value(value, places):
    return format(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP), "f")


def aggregate(distribution, *, probability):
    total = sum(weight for _, weight in distribution)
    if probability:
        return sum(value * weight for value, weight in distribution) / total
    cumulative = Decimal(0)
    for value, weight in sorted(distribution):
        cumulative += weight
        if cumulative * 2 >= total:
            return value
    raise ValueError("Empty economic forecast cell")


def encode(rows):
    return csv_text(FIELDS, ([row[key] for key in FIELDS] for row in rows)).encode()


def load(path=SUMMARY):
    with Path(path).open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(FIELDS):
            raise ValueError("Unexpected public cohort summary columns")
        rows = list(reader)
    if not rows:
        return None, []
    cells = display_cells()
    keys = {tuple(r[k] for k in CELL) for r in rows}
    if len(rows) != len(keys) or not keys <= cells.keys():
        raise ValueError("Public cohort summary has unknown or duplicate cells")
    dates = {date.fromisoformat(r["extracted_on"]).isoformat() for r in rows}
    if len(dates) != 1:
        raise ValueError("Expected a single cohort extract date")
    for row in rows:
        key = tuple(row[k] for k in CELL)
        value = Decimal(row["value"])
        if (None in row or not value.is_finite() or row["value"] != display_value(value, cells[key])
                or int(row["respondents"]) < 2):
            raise ValueError(f"Invalid public summary for {key}")
    return dates.pop(), rows


def summarize(directory, extracted_on, out=SUMMARY):
    vintage = date.fromisoformat(extracted_on).isoformat()
    cells = display_cells()
    distributions = defaultdict(list)
    counts = {}
    for kind in ("economic", "probabilities"):
        with (Path(directory) / (kind + ".csv")).open(newline="") as stream:
            reader = csv.DictReader(stream)
            if not {"value", "weight", "frequency", "respondents", "extract_rows"} <= set(reader.fieldnames or ()):
                raise ValueError(f"Regenerate {kind}.csv with the current EEAI warehouse query")
            length = 0
            expected_length = None
            for length, row in enumerate(reader, 1):
                total_rows = int(row["extract_rows"])
                if expected_length is not None and expected_length != total_rows:
                    raise ValueError(f"Inconsistent row count in {kind} extract")
                expected_length = total_rows
                target = row["target_variable_id"]
                if row["cohort"] not in COHORTS:
                    raise ValueError("Unknown survey cohort")
                if kind == "economic":
                    key = (ALIASES.get(target, target), row["target_year"], row["scenario"],
                           "p" + row["percentile"], "", row["cohort"])
                    if key not in cells:
                        continue  # The warehouse also includes questions outside the dashboard survey.
                else:
                    if target in ("physical_systems", "reliability"):
                        continue  # Older private extracts also include the two milestone questions.
                    if target != "ai_progress_scenario":
                        raise ValueError("Unknown probability target")
                    key = ("scenario_probabilities", "2030", "unconditional", "probability", row["bin_id"], row["cohort"])
                    if key not in cells:
                        raise ValueError("Unknown probability cell")
                value, weight = Decimal(row["value"]), Decimal(row["weight"])
                frequency = int(row["frequency"])
                if not value.is_finite() or not weight.is_finite() or weight <= 0 or frequency < 1:
                    raise ValueError("Invalid weighted survey value")
                if kind == "probabilities" and not 0 <= value <= 100:
                    raise ValueError("Invalid survey probability")
                respondents = int(row["respondents"])
                if respondents < 2 or counts.setdefault(key, respondents) != respondents:
                    raise ValueError(f"Invalid cohort count for {key}")
                distributions[key].append((value, weight * frequency))
            if expected_length is not None and length != expected_length:
                raise ValueError(f"Incomplete {kind} extract")
    rows = []
    scenario_values = defaultdict(list)
    for key, places in cells.items():
        if key not in distributions:
            continue
        value = aggregate(distributions[key], probability=key[3] == "probability")
        if key[0] == "scenario_probabilities":
            scenario_values[key[-1]].append(value)
        rows.append(dict(zip(CELL, key, strict=True), value=display_value(value, places),
                         respondents=str(counts[key]), extracted_on=vintage))
    if any(abs(sum(values) - 100) > Decimal("0.000001") for values in scenario_values.values() if len(values) == 3):
        raise ValueError("Scenario probabilities do not sum to 100")
    out = Path(out)
    with NamedTemporaryFile(dir=out.parent, delete=False) as tmp:
        tmp.write(encode(rows))
    try:
        load(tmp.name)
        os.replace(tmp.name, out)
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    return out
