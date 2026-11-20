import csv
from decimal import Decimal

import pytest

from eeai import human


def test_weighted_statistics_and_display_precision():
    values = [(Decimal("7"), Decimal("0.2")), (Decimal("3"), Decimal("0.1")),
              (Decimal("2"), Decimal("0.1"))]
    assert human.aggregate(values, probability=False) == 3  # exactly half the weight at 3
    assert human.aggregate(values, probability=True) == Decimal("4.75")
    assert human.display_value(Decimal("1.25"), 1) == "1.3"


def test_private_columns_cannot_enter_public_summary(tmp_path):
    summary = tmp_path / "summary.csv"
    rows = human.load()[1]
    rows[0]["private_note"] = "fictional test response"
    public = human.encode(rows)
    assert public == human.SUMMARY.read_bytes()
    summary.write_bytes(public.replace(b"question,", b"private_note,question,", 1))
    with pytest.raises(ValueError, match="columns"):
        human.load(summary)


def test_truncated_private_input_preserves_previous_summary(tmp_path):
    path = tmp_path / "economic.csv"
    fields = ["target_variable_id", "target_year", "scenario", "percentile", "cohort", "value",
              "weight", "frequency", "respondents", "extract_rows"]
    with path.open("w") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        writer.writerow(["gdp", "2030", "unconditional", 50, "superforecaster", 3, 1, 34, 34, 2])
    out = tmp_path / "summary.csv"
    out.write_text("previous summary")
    with pytest.raises(ValueError, match="Incomplete economic extract"):
        human.summarize(tmp_path, "2026-11-19", out)
    assert out.read_text() == "previous summary"


def test_sparse_summary_keeps_available_cells(tmp_path):
    row = human.load()[1][0]
    summary = tmp_path / "human.csv"
    summary.write_bytes(human.encode([row]))
    assert human.load(summary) == (row["extracted_on"], [row])
    summary.write_bytes(human.encode([]))
    assert human.load(summary) == (None, [])
    summary.write_bytes(human.encode([row, row]))
    with pytest.raises(ValueError, match="duplicate"):
        human.load(summary)
