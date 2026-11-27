"""Replays using published releases, with no network or installation credentials."""
import io
import json
import tempfile
from types import SimpleNamespace
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from eeai import baselines, build, config, decisions, export, resolve, survey
from eeai.__main__ import main
from dashboard import resolutions


class ResolutionTest(unittest.TestCase):
    def setUp(self):
        self.doc = survey.load()
        self.q = {q["id"]: q for q in self.doc["questions"]}
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        override = patch.object(config, "RESULTS", self.root)
        override.start()
        self.addCleanup(override.stop)

    def test_fred_requests_set_the_observation_and_vintage_windows(self):
        key = self.root / "key"
        key.write_text("fixture")
        day = "2024-02-02"
        periods = ["2024-01-01"]
        with patch("fri_forecaster.keys.value", return_value=None), patch.dict(
                "os.environ", {"FRED_API_KEY_FILE": str(key)}):
            for latest, start in ((False, periods[0]), (True, day)):
                response = io.BytesIO(b'{"count": 0, "observations": []}')
                with patch.object(resolve, "urlopen", return_value=response) as request:
                    self.assertEqual(resolve.fetch("UNRATE", periods, day, latest=latest), [])
                url = urlparse(request.call_args.args[0])
                args = parse_qs(url.query)
                self.assertEqual(url.hostname, "api.stlouisfed.org")
                self.assertEqual(args["api_key"], ["fixture"])
                self.assertEqual(args["realtime_start"], [start])
                self.assertEqual(args["realtime_end"], [day])
                self.assertEqual(args["observation_start"], periods)
                self.assertEqual(args["observation_end"], periods)

    def test_published_releases_through_page_and_download(self):
        # BLS 2024-02-02 Employment Situation; BEA September 2024 annual update
        # and 2025-01-30 GDP advance release. Annual rates are in percent.
        examples = [
            ("unemployment", "2024", "2024-02-02", [3.7], 3.7),
            ("gdp", "2025", "2025-01-30", [-2.2, 6.1, 2.5, 2.9, 2.8], 2.39),
        ]
        db = self.root / "resolutions.sqlite"
        for qid, year, vintage, values, expected in examples:
            q = self.q[qid]
            periods = resolve.dates(q["resolution"]["method"], int(year))
            rows = [dict(date=p, value=str(v), realtime_start=vintage, realtime_end="9999-12-31")
                    for p, v in zip(periods, values, strict=True)]
            self.assertIsNone(resolve.outcome_for(q, periods, {q["resolution"]["series"]: rows}, vintage[:8] + "01"))
            outcome = resolve.outcome_for(q, periods, {q["resolution"]["series"]: rows}, vintage)
            self.assertEqual(round(outcome["value"], 2), expected)
            self.assertEqual(dict(survey.history(config.HISTORY)[qid])[year + "-01-01"], expected)
            resolutions.record(db, qid, year, q["resolution"], outcome)
            q["horizons"] = [{"id": year, "text": year}]
        records = resolutions.snapshot(db)
        blob = build.build(self.doc, runs=[], outcomes=records)
        self.assertIn('"vintage": "2025-01-30"', build.page(blob))
        path = self.root / "out.zip"
        export.bundle(path, self.doc, [], outcomes=records)
        with zipfile.ZipFile(path) as archive:
            data = json.loads(archive.read("resolutions.json"))
        for row in data:
            q = next(q for q in blob["questions"] if q["id"] == row["question"])
            self.assertEqual(q["horizons"][0]["actual"]["inputs"], row["inputs"])

    def test_refresh_imports_reviewed_releases_and_exports_both(self):
        q = self.q["ai_electricity"]
        reviewed = self.root / "reviewed"
        reviewed.mkdir()
        for vintage, value in [("2031-02-10", 2.0), ("2031-03-20", 2.2)]:
            decision = dict(question=q["id"], horizon="2030", version=1, value=value,
                            source="Example report", period="2030", vintage=vintage,
                            reviewer="Energy panel", rationale="Annual US estimate")
            (reviewed / (vintage + ".json")).write_text(json.dumps(decision))
        self.doc["questions"] = [q]
        with patch.object(survey, "load", return_value=self.doc):
            resolve.refresh(date(2031, 4, 1))
            resolve.refresh(date(2031, 4, 2))
        records = resolutions.snapshot(self.root / "resolutions.sqlite")
        actual = next(h for h in build.build(self.doc, runs=[], outcomes=records)["questions"][0]["horizons"]
                      if h["id"] == "2030")["actual"]
        self.assertEqual(actual["value"], 2.0)
        self.assertEqual([r["value"] for r in actual["revisions"]], [2.0, 2.2])
        path = self.root / "out.zip"
        export.bundle(path, self.doc, [], outcomes=records)
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(json.loads(archive.read("resolutions.json"))[0]["revisions"], actual["revisions"])

    def test_fred_batch_reads_shared_series_once_and_handles_clipped_vintages(self):
        q = self.q["unemployment"]
        second = dict(q, id="another_question")
        self.doc["questions"] = [q, second]
        calls = []
        def reader(key, periods, as_of, since=None):
            calls.append((key, since))
            rows = []
            for start, end, value in [("2027-02-01", "2027-02-28", 4.0),
                                      ("2027-03-01", "9999-12-31", 4.1)]:
                if start <= as_of and (since is None or end >= since):
                    rows.append(dict(date="2027-01-01", value=str(value),
                                     realtime_start=max(start, since or start), realtime_end=end))
            return rows
        with patch.object(survey, "load", return_value=self.doc):
            for day in (date(2027, 2, 15), date(2027, 3, 10), date(2027, 4, 15)):
                resolve.refresh(day, reader)
        self.assertEqual(calls, [("UNRATE", None), ("UNRATE", "2027-02-14"), ("UNRATE", "2027-03-09")])
        head, histories = resolutions.history(self.root / "resolutions.sqlite")
        self.assertEqual((head, len(histories)), (4, 2))
        for records in histories.values():
            self.assertEqual([r["vintage"] for r in records], ["2027-02-01", "2027-03-01"])

    def test_job_shares_reproduce_survey_examples(self):
        counts = {"USINFO": 2963, "USFIRE": 9165, "USPBS": 22668, "USGOOD": 21631,
                  "USTPU": 28799, "USEHS": 26033, "USLAH": 16716, "USSERV": 5917, "CLF16OV": 167308}
        for qid, expected in [("jobs_business_analytical", 20.8), ("jobs_skilled_trade_industrial", 12.9),
                              ("jobs_care_service", 46.3)]:
            rule = self.q[qid]["resolution"]
            values = {key: {"2024-01-01": counts[key]} for key in resolve.source_ids(rule)}
            self.assertEqual(round(resolve.calculate(rule, values, ["2024-01-01"]), 1), expected)

    def test_productivity_income_and_labor_share_units(self):
        periods = resolve.dates("q4_five_year_growth", 2030)
        self.assertEqual(periods, [f"{y}-10-01" for y in range(2025, 2030)])
        income = self.q["median_household_income"]["resolution"]
        inputs = {income["series"]: {"2023-01-01": 84730, "2025-01-01": 87460},
                  income["nominal"]: {"2023-01-01": 80610}}
        self.assertEqual(resolve.calculate(income, inputs, ["2023-01-01"]), 80610)
        self.assertAlmostEqual(resolve.calculate(income, inputs, ["2025-01-01"]), 87460 * 80610 / 84730)
        share = self.q["labor_share"]["resolution"]
        value = resolve.calculate(share, {share["series"]: {"2023-01-01": 96.618}}, ["2023-01-01"])
        self.assertAlmostEqual(value, dict(survey.history(config.HISTORY)["labor_share"])["2023-01-01"])

    def test_failed_baseline_refresh_preserves_prior_snapshot(self):
        day = date(2026, 11, 19)
        rows = lambda values: [dict(date=k, value=str(v), realtime_start=str(day), realtime_end=str(day))
                               for k, v in values.items()]
        def reader(key, periods, as_of, latest=False):
            self.assertTrue(latest)
            return rows({"2025-01-01": 4, "2026-01-01": 4.3})
        with patch.object(survey, "load", return_value={"questions": [self.q["unemployment"]]}):
            baselines.refresh(day, reader)
            source = baselines.current(day)
            before = source.read_bytes()
            self.assertEqual(survey.history(source)["unemployment"][-1], ("2026-01-01", 4.3))
            with self.assertRaises(ValueError):
                baselines.refresh(day, lambda *args, **kwargs: [])
            self.assertEqual(source.read_bytes(), before)

    def test_refresh_does_not_advance_forecast_baseline_on_resolution_failure(self):
        with patch.object(resolve, "refresh", side_effect=RuntimeError("missing evidence")), patch.object(baselines, "refresh") as refresh:
            with self.assertRaisesRegex(RuntimeError, "missing evidence"):
                main(["refresh"])
            refresh.assert_not_called()

    def test_build_pins_the_chosen_baseline_bytes_and_source_date(self):
        baseline = self.root / "baselines"
        baseline.mkdir()
        source = baseline / "2025-11-21.csv"
        history = config.HISTORY.read_bytes()
        source.write_bytes(history)
        site = self.root / "site"
        row = {"run_id": "test", "label": "fixture", "run_date": "2025-01-01", "model": "fixture",
               "question_id": "gdp", "forecasts": {}, "rationale": None}
        (self.root / "test.jsonl").write_text(json.dumps(row))
        assemble = build.page

        def concurrent_refresh(blob):
            self.assertEqual(blob["baseline"], {"source": "fred", "as_of": "2025-11-21"})
            replacement = baseline / "temporary"
            replacement.write_bytes(b"concurrent replacement")
            replacement.replace(source)
            (baseline / "2025-11-22.csv").write_bytes(b"newer snapshot")
            return assemble(blob)

        args = SimpleNamespace(runs=str(self.root), out=None, json=None, site=str(site))
        with patch.object(build, "page", concurrent_refresh), patch.object(build, "load_runs", return_value=[("test", [row])]):
            build.main(args)
        with zipfile.ZipFile(site / export.NAME) as archive:
            self.assertEqual(json.loads(archive.read("baseline.json")), {"source": "fred", "as_of": "2025-11-21"})
            self.assertEqual(archive.read("history.csv"), history)
        self.assertIn('"as_of": "2025-11-21"', (site / "index.html").read_text())
        source.unlink()
        (baseline / "2025-11-22.csv").unlink()
        self.assertEqual(baselines.snapshot(), ({"source": "survey", "as_of": None}, history))

    def test_adjudication_and_correction(self):
        decision = dict(question="ai_electricity", horizon="2030", version=1, value=2.0,
                        source="Example study table 2", rationale="Reviewed nationwide estimate",
                        reviewer="Example reviewer", period="2030", vintage="2031-05-01")
        path = self.root / "decision.json"
        path.write_text(json.dumps(decision))
        with self.assertRaises(ValueError):
            decisions.apply(path, date(2030, 11, 1))
        today = date(2031, 6, 1)
        decisions.apply(path, today)
        db = self.root / "resolutions.sqlite"
        key = ("ai_electricity", "2030", 1)
        previous = resolutions.snapshot(db)[key]
        path.write_text(json.dumps(dict(decision, previous=previous, value=2.1, correction_reason="Erratum")))
        decisions.apply(path, today)
        self.assertEqual(resolutions.snapshot(db)[key]["supersedes"], previous)
        with self.assertRaises(ValueError):
            decisions.apply(path, today)
