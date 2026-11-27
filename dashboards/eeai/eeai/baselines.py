"""Refresh the survey's annual chart points in one dated, atomic snapshot."""
import csv
import fcntl
import io
import os
from datetime import date, datetime, timezone
from tempfile import NamedTemporaryFile

from . import config, resolve, survey


def current(as_of=None):
    root = config.RESULTS / "baselines"
    cutoff = str(as_of or datetime.now(timezone.utc).date())
    files = sorted(p for p in root.glob("????-??-??.csv") if p.stem <= cutoff)
    return files[-1] if files else config.HISTORY


def snapshot():
    """Read the chosen inode once so the page and export share bytes and date."""
    source = current()
    if source == config.HISTORY:
        return {"source": "survey", "as_of": None}, source.read_bytes()
    return {"source": "fred", "as_of": date.fromisoformat(source.stem).isoformat()}, source.read_bytes()


def refresh(as_of=None, reader=resolve.fetch):
    day = as_of or datetime.now(timezone.utc).date()
    root = config.RESULTS / "baselines"
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        prior = survey.history(current(day))
        seed = survey.history(config.HISTORY)
        report = {}
        for q in survey.load()["questions"]:
            rule = q["resolution"]
            if q["resolver"] != "fred":
                continue
            series = q["history"]
            first_year = int(seed[series][-1][0][:4])
            first_period = resolve.dates(rule["method"], first_year)[0]
            evidence = {key: reader(key, resolve.input_dates(rule, key, [first_period, day.isoformat()]),
                                    day.isoformat(), latest=True)
                        for key in resolve.source_ids(rule)}
            original = dict(seed[series])
            values = dict(prior[series])
            for year in range(first_year, day.year + 1):
                period = f"{year}-01-01"
                result = resolve.outcome_for(q, resolve.dates(rule["method"], year), evidence, day.isoformat())
                if result:
                    values[period] = result["value"]
                elif period in values:
                    raise ValueError(f"{series} lost coverage for {period}")
            prior[series] = sorted(values.items())
            overlap = seed[series][-1][0]
            report[series] = dict(overlap=overlap, survey=original[overlap], refreshed=values[overlap],
                                  through=prior[series][-1][0])
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(("series", "date", "value"))
        for series, points in prior.items():
            writer.writerows((series, date, value) for date, value in points)
        target = root / f"{day}.csv"
        with NamedTemporaryFile(dir=root, delete=False) as temporary:
            temporary.write(out.getvalue().encode())
        os.replace(temporary.name, target)
        return report
