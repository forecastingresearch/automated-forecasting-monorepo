"""Portable cohort forecast records, stored as immutable dated CSV snapshots."""
import csv
import io
import math
import os
import tempfile
from datetime import date
from pathlib import Path

from .download import csv_text

KEY = ("project", "instrument", "survey", "question", "horizon", "condition", "option",
       "elicited_statistic", "cohort", "aggregation")
FIELDS = (*KEY, "value", "unit", "respondents", "source_target", "source_extract", "extract_sha256")


def encode(records):
    return csv_text(FIELDS, ([row[field] for field in FIELDS] for row in records)).encode()


def decode(data):
    rows = list(csv.DictReader(io.StringIO(data.decode())))
    seen = set()
    for row in rows:
        key = tuple(row[k] for k in KEY)
        if (set(row) != set(FIELDS) or key in seen or not math.isfinite(float(row["value"]))
                or int(row["respondents"]) < 1 or any(not row[k] for k in FIELDS if k != "option")):
            raise ValueError(f"Invalid human forecast {key}")
        seen.add(key)
    if not rows:
        raise ValueError("Empty human forecast snapshot")
    return rows


def store(directory, extracted_on, records):
    data = encode(records)
    decode(data)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (date.fromisoformat(extracted_on).isoformat() + ".csv")
    with tempfile.NamedTemporaryFile(dir=directory) as temporary:
        temporary.write(data)
        temporary.flush()
        try:
            os.link(temporary.name, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError(f"Conflicting human forecast snapshot for {extracted_on}")
    return path


def latest(directory):
    paths = sorted(Path(directory).glob("????-??-??.csv"))
    if paths:
        path = paths[-1]
        return path.stem, decode(path.read_bytes())
    return None, []
