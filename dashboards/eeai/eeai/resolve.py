"""Resolve EEAI targets against the FRED vintages with complete evidence."""
import json
import math
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import urlopen

from . import config, survey
from dashboard import resolutions


def dates(method, year):
    if method in ("january", "employment_share", "income_2023_dollars", "anchored_index"):
        return [f"{year}-01-01"]
    if method == "q4_five_year_growth":
        return [f"{y}-10-01" for y in range(year - 5, year)]
    if method == "five_year_growth":
        return [f"{y}-01-01" for y in range(year - 5, year)]
    raise ValueError(f"Unknown resolution method {method}")


def fetch(series, periods, as_of, *, latest=False, since=None):
    from fri_forecaster import keys
    key = keys.value("FRED_API_KEY")
    if not key and os.environ.get("FRED_API_KEY_FILE"):
        key = Path(os.environ["FRED_API_KEY_FILE"]).read_text().strip()
    if not key:
        raise ValueError("Set FRED_API_KEY or FRED_API_KEY_FILE to read economic observations")
    query = urlencode(dict(series_id=series, api_key=key, file_type="json",
                           observation_start=periods[0], observation_end=periods[-1],
                           realtime_start=as_of if latest else (since or periods[0]), realtime_end=as_of))
    try:
        with urlopen("https://api.stlouisfed.org/fred/series/observations?" + query, timeout=30) as response:
            data = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"FRED rejected {series} (HTTP {exc.code})") from None
    except URLError:
        raise RuntimeError(f"Cannot reach the FRED API for {series}") from None
    if len(data["observations"]) != int(data["count"]):
        raise ValueError(f"Incomplete FRED response for {series}")
    return data["observations"]


def source_ids(rule):
    if rule["method"] == "employment_share":
        return [*rule["numerators"], rule["denominator"]]
    if rule["method"] == "income_2023_dollars":
        return [rule["series"], rule["nominal"]]
    return [rule["series"]]


def input_dates(rule, source, periods):
    if rule["method"] == "anchored_index":
        return sorted(set([rule["anchor_date"], *periods]))
    if rule["method"] == "income_2023_dollars":
        if source == rule["nominal"]:
            return [rule["base_date"]]
        return sorted(set([rule["base_date"], *periods]))
    return periods


def calculate(rule, values, periods):
    method = rule["method"]
    if method == "employment_share":
        counts = [values[key][periods[0]] for key in rule["numerators"]]
        denominator = values[rule["denominator"]][periods[0]]
        if min(counts) < 0 or denominator <= 0:
            raise ValueError("Invalid employment or labor force count")
        return 100 * sum(counts) / denominator
    observation = values[rule["series"]]
    if method in ("five_year_growth", "q4_five_year_growth"):
        if min(observation.values()) < -100:
            raise ValueError("Invalid annual growth rate")
        return 100 * (math.prod(1 + observation[p] / 100 for p in periods) ** (1 / 5) - 1)
    value = observation[periods[0]]
    if method == "anchored_index":
        return rule["anchor_percent"] * value / observation[rule["anchor_date"]]
    if method == "income_2023_dollars":
        # Rebasing cancels the release's dollar basis. In the base year the
        # real value in base-year dollars equals the nominal value.
        base = rule["base_date"]
        return value * values[rule["nominal"]][base] / observation[base]
    if method == "january":
        return value
    raise ValueError(f"Unknown method {method}")


def outcome_history(q, periods, evidence, as_of):
    rule = q["resolution"]
    required = {key: input_dates(rule, key, periods) for key in source_ids(rule)}
    rows = {key: [r for r in evidence[key] if r["date"] in dates and r["value"] != "."]
            for key, dates in required.items()}
    vintages = sorted({r["realtime_start"] for values in rows.values() for r in values})
    last_value = None
    for vintage in vintages:
        if vintage > as_of:
            break
        inputs = {key: {r["date"]: float(r["value"]) for r in values
                        if r["realtime_start"] <= vintage <= r["realtime_end"]}
                  for key, values in rows.items()}
        if any(inputs[key].keys() != set(dates) for key, dates in required.items()):
            continue
        if not all(math.isfinite(v) for values in inputs.values() for v in values.values()):
            raise ValueError("Nonfinite FRED observation")
        value = calculate(rule, inputs, periods)
        if not q["bounds"][0] <= value <= q["bounds"][1]:
            raise ValueError(f"Outcome outside question bounds: {value}")
        if last_value == value:
            continue
        last_value = value
        if len(inputs) == 1:
            key, = inputs
            yield dict(value=value, unit=q["unit"], vintage=vintage, inputs=inputs[key],
                       source="https://fred.stlouisfed.org/series/" + key)
        else:
            yield dict(value=value, unit=q["unit"], vintage=vintage, inputs=inputs,
                       sources=["https://fred.stlouisfed.org/series/" + key for key in inputs])


def outcome_for(q, periods, evidence, as_of):
    return next(outcome_history(q, periods, evidence, as_of), None)


def read_target(q, periods, day, reader=fetch, *, history=False):
    rule = q["resolution"]
    evidence = {key: reader(key, input_dates(rule, key, periods), day) for key in source_ids(rule)}
    records = outcome_history(q, periods, evidence, day)
    return list(records) if history else next(records, None)


class FredResolver:
    def __init__(self, reader=fetch):
        self.reader = reader

    def refresh(self, requests, *, as_of, after):
        day = as_of.isoformat()
        signatures = [[*r.target, r.rule] for r in requests]
        bookmark = after["day"] if after and signatures == after["targets"] else None
        if after and day < after["day"]:
            raise ValueError("Cannot rewind a refresh; use replay for historical inspection")
        # One extra day establishes the value immediately before the bookmark.
        # Otherwise FRED clips realtime_start and unchanged inputs look newly published.
        since = (date.fromisoformat(bookmark) - timedelta(days=1)).isoformat() if bookmark else None
        windows = {}
        for request in requests:
            periods = dates(request.rule["method"], int(request.target.horizon))
            for key in source_ids(request.rule):
                windows.setdefault(key, set()).update(input_dates(request.rule, key, periods))
        options = {"since": since} if since else {}
        evidence = {key: self.reader(key, sorted(periods), day, **options) for key, periods in windows.items()}
        observations = []
        for request in requests:
            periods = dates(request.rule["method"], int(request.target.horizon))
            for outcome in outcome_history(request.params, periods, evidence, day):
                vintage = outcome.pop("vintage")
                if bookmark and vintage < bookmark:
                    continue
                observations.append(resolutions.Observation(
                    request.target, vintage, vintage, outcome.pop("value"), outcome))
        return resolutions.RefreshBatch(observations, {"day": day, "targets": signatures})


def refresh(as_of=None, reader=fetch, path=None):
    from .decisions import ReviewedResolver

    as_of = as_of or datetime.now(timezone.utc).date()
    path = path or config.RESULTS / "resolutions.sqlite"
    doc = survey.load()
    questions = list(doc["questions"])
    if "scenarios" in doc:
        questions.append({"id": "ai_scenario", "resolver": "reviewed", "resolution": doc["scenarios"]["resolution"],
                          "horizons": [{"id": "2030"}]})
    requests = []
    for q in questions:
        rules = [q["resolution"], *q.get("previous_rules", {}).values()]
        for rule in rules:
            for horizon in q["horizons"]:
                year = horizon["id"]
                if date(int(year), 1, 1) <= as_of:
                    target = resolutions.Target(q["id"], year, rule["version"])
                    plugin = rule.get("resolver", q["resolver"])
                    requests.append(resolutions.Request(target, plugin, rule, dict(q, resolution=rule)))
    plugins = {"fred": FredResolver(reader), "reviewed": ReviewedResolver(config.RESULTS / "reviewed", doc)}
    resolutions.refresh(path, requests, plugins, as_of=as_of)
    return len(resolutions.snapshot(path))
