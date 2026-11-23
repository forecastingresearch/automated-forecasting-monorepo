"""EEAI's economy model: the definition, the instrument, a run without calls, the metalog, the identities, the pages."""
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from eeai import config
from eeai.model import build as mbuild
from eeai.model import instrument as I
from eeai.model import run, synthetic
from eeai.model import spec as M

try:
    import numpy as np
except ImportError:                      # the simulation needs numpy (eeai[model]); the rest does not
    np = None
needs_numpy = unittest.skipIf(np is None, "numpy is not installed (pip install -e 'dashboards/eeai[model]')")

TODAY = date(2026, 11, 18)
MEMBERS = [{"key": "m-a", "label": "Model A", "model": "anthropic/m-a", "reasoning": "max"},
           {"key": "m-b", "label": "Model B", "model": "openai/m-b", "reasoning": "xhigh"}]


class TestDefinition(unittest.TestCase):
    def setUp(self):
        self.spec = M.load()

    def test_the_counts_are_the_design_notes(self):
        comps, bases = M.components(self.spec), M.baselines(self.spec)
        self.assertEqual(len(comps), 760)                      # per scenario and year
        self.assertEqual(len(bases), 711)
        self.assertEqual(M.n_sets(self.spec), 760 * 3 * 9 + 711)
        self.assertEqual(M.n_sets(self.spec), 21231)
        self.assertEqual(len({c["id"] for c in comps + bases}), 760 + 711)
        self.assertEqual(sum(1 for c in comps if c["per"] == "cell"), 484)

    def test_the_scenarios_are_copied_in_and_every_transform_is_known(self):
        survey = json.loads((config.QUESTIONS).read_text(encoding="utf-8"))
        # The wording, verbatim; the survey's resolution rule for the scenario question is not the model's.
        wording = {k: v for k, v in survey["scenarios"].items() if k != "resolution"}
        self.assertEqual(self.spec["scenarios"], wording)
        for c in M.components(self.spec) + M.baselines(self.spec):
            self.assertIn(c["transform"], ("none", "log", "logit"))


class TestInstrument(unittest.TestCase):
    def setUp(self):
        self.spec = M.load()
        self.record = synthetic.placeholder_record(self.spec)

    def test_one_call_asks_everything_and_a_split_partitions_it(self):
        (one,) = I.calls(self.spec)
        everything = I.asked(self.spec, one)
        self.assertEqual(sum(len(p) for p in everything.values()), 21231)
        for split in ("scenario", "block"):
            seen = {}
            for call in I.calls(self.spec, split):
                for cid, pairs in I.asked(self.spec, call).items():
                    for p in pairs:
                        self.assertNotIn((cid, p), seen, f"{split}: {cid} {p} asked twice")
                        seen[(cid, p)] = call["id"]
            self.assertEqual(len(seen), 21231, split)

    def test_the_prompt_carries_the_definitions_and_no_advice(self):
        prompt, keys = I.build_prompt(self.spec, I.calls(self.spec)[0], self.record, TODAY)
        self.assertTrue(prompt.startswith("Today is 2026-11-18."))
        for needle in ("--- Q.<industry id>: Real value added", "--- sigma.<industry id>.<occupation id>",
                       "base.N0.construction: 1,320", "submit_forecast ONCE", "scenario_probabilities"):
            self.assertIn(needle, prompt)
        for advice in ("base rate", "superforecast", "think step", "reference class"):
            self.assertNotIn(advice, prompt.lower())
        self.assertEqual(len(keys), 760 + 711 + 1 + 3 * 70)
        # A retry asks only for what is missing.
        retry, rkeys = I.build_prompt(self.spec, I.calls(self.spec)[0], self.record, TODAY, only={"Q.retail", "why.base"})
        self.assertEqual(rkeys, ["Q.retail", "why.base"])
        self.assertIn("Still needed: Q.retail", retry)
        self.assertNotIn("sigma.<industry id>", retry)

    def test_clean_cell_keeps_what_was_asked_and_names_the_rest(self):
        every = M.by_id(self.spec)
        share, index = every["sigma.retail.sales"], every["Q.retail"]
        pairs = [("2026", "slow"), ("2027", "slow"), ("2028", "slow"), ("2029", "slow")]
        raw = {"forecasts": {"2026": {"slow": {"q05": .1, "q25": .2, "q50": .3, "q75": .4, "q95": .5}},
                             "2027": {"slow": {"q05": 0, "q25": .2, "q50": .3, "q75": .4, "q95": .5}},
                             "2028": {"slow": {"q05": .1, "q25": .3, "q50": .3, "q75": .4, "q95": .5}}}}
        got, problems = I.clean_cell(self.spec, share, raw, pairs)
        self.assertEqual(list(got), ["2026"])
        self.assertEqual(len(problems), 3)
        self.assertTrue(any("outside" in p for p in problems) and any("strictly" in p for p in problems)
                        and any("2029/slow: missing" in p for p in problems))
        neg = {"forecasts": {"2026": {"slow": {"q05": -1, "q25": .2, "q50": .3, "q75": .4, "q95": .5}}}}
        self.assertEqual(I.clean_cell(self.spec, index, neg, pairs[:1])[0], {})

    def test_probabilities(self):
        self.assertEqual(I.clean_probabilities(self.spec, {"scenario_probabilities": {"slow": 30, "moderate": 50, "rapid": 20.5}})[1], [])
        self.assertIsNone(I.clean_probabilities(self.spec, {"scenario_probabilities": {"slow": 30, "moderate": 30, "rapid": 20}})[0])


class TestRun(unittest.TestCase):
    def setUp(self):
        self.spec = M.load()
        self.record = synthetic.placeholder_record(self.spec)

    def _rows(self, member, harness_run=None, split=None):
        return run.ask(member, self.spec, self.record, TODAY, "2026-11-18T0000Z", split=split,
                       harness_run=harness_run or synthetic.harness_run(self.spec, self.record, TODAY), synthetic=True)

    def test_a_call_becomes_one_row_per_component(self):
        rows = self._rows(MEMBERS[0])
        self.assertEqual(len(rows), 760 + 711)
        call = rows[0]["call"]
        self.assertEqual((call["values"], call["values_asked"], call["attempts"]), (21231, 21231, {"all": 1}))
        self.assertTrue(all(r["call"] is None for r in rows[1:]))
        self.assertTrue(all(r["problems"] == [] for r in rows))
        self.assertEqual(len(call["rationales"]), 1 + 3 * 70)
        self.assertEqual(rows[0]["instrument"], "eeai-model-v0")
        self.assertEqual(call["blocked_urls"], list(config.BLOCKED_URLS))

    def test_the_call_gets_the_models_own_limits(self):
        seen = {}
        full = synthetic.harness_run(self.spec, self.record, TODAY)

        def spy(**kw):
            seen.update(kw)
            return full(**kw)
        self._rows(MEMBERS[0], spy)
        self.assertEqual((seen["max_turns"], seen["timeout"]), (config.MODEL_MAX_TURNS, config.MODEL_TIMEOUT))
        self.assertEqual(seen["system"], " ")
        self.assertEqual(seen["min_research"], 0)

    def test_a_thin_answer_is_asked_again_for_the_missing_only(self):
        full = synthetic.harness_run(self.spec, self.record, TODAY)
        asked = []

        def thin_then_full(**kw):
            asked.append(list(kw["allowed_keys"]))
            res = full(**kw)
            if len(asked) == 1:
                res["cells"] = {k: v for k, v in res["cells"].items() if not k.startswith("sigma.")}
            return res
        rows = self._rows(MEMBERS[0], thin_then_full)
        self.assertEqual(len(asked), 2)
        self.assertTrue(asked[1] and all(k.startswith("sigma.") for k in asked[1]))
        self.assertEqual(len(asked[1]), 484)
        self.assertEqual(rows[0]["call"]["values"], 21231)

    def test_a_split_run_merges_into_the_same_rows(self):
        rows = self._rows(MEMBERS[0], split="scenario")
        self.assertEqual(rows[0]["call"]["values"], 21231)
        self.assertEqual(set(rows[0]["call"]["attempts"]), {"base", "slow", "moderate", "rapid"})

    def test_synthetic_rows_never_go_to_results(self):
        args = SimpleNamespace(synthetic=True, out=None, today=None, smoke=True, models=None)
        with self.assertRaises(SystemExit):
            run.main(args)

    def test_synthetic_answers_work_with_a_real_record(self):
        # The real baselines.csv offers no automation baselines and can hold an
        # empty CPS cell (a share of 0); made-up answers still cover every component.
        real = {k: v for k, v in self.record.items() if not k.split(".")[1] in ("sA0", "sM0", "rA0", "rM0")}
        cell = next(k for k in real if k.startswith("base.sigma0."))
        real[cell] = {**real[cell], "value": 0.0}
        keys = [c["id"] for c in M.components(self.spec) + M.baselines(self.spec)]
        cells, _ = synthetic.answer(self.spec, real, "Model A", keys, TODAY)
        self.assertEqual(len(cells), len(keys))
        q = cells[cell]["forecasts"]["2025"]["base"]
        self.assertTrue(0 < q["q05"] < q["q95"] < 1)


@needs_numpy
class TestMetalog(unittest.TestCase):
    def test_the_fit_passes_through_the_quantiles_and_draws_reproduce_them(self):
        from eeai.model import metalog
        q = np.array([[0.9, 0.97, 1.0, 1.03, 1.12], [0.01, 0.02, 0.03, 0.05, 0.09], [-1.0, 0.0, 0.5, 1.0, 3.0]])
        f = metalog.Fit(q, np.array([1, 2, 0]))
        self.assertTrue(f.metalog.all())
        np.testing.assert_allclose(f.quantile(np.tile(f.probs[:, None], (1, 3))), q.T, rtol=1e-9, atol=1e-12)
        d = f.draw(np.random.default_rng(1), 200000)
        np.testing.assert_allclose(np.quantile(d, f.probs, axis=0).T, q, rtol=0.01, atol=0.01)
        self.assertTrue((d[:, 0] > 0).all() and ((d[:, 1] > 0) & (d[:, 1] < 1)).all())

    def test_a_metalog_that_is_not_increasing_falls_back(self):
        from eeai.model import metalog
        q = np.array([[0.1, 0.2, 0.3, 0.31, 0.9]])               # nearly flat, then a long tail
        f = metalog.Fit(q, np.array([2]))
        self.assertFalse(f.metalog[0])
        self.assertEqual(f.fallback_rate, 1.0)
        d = f.draw(np.random.default_rng(2), 200000)
        np.testing.assert_allclose(np.quantile(d[:, 0], f.probs), q[0], atol=0.01)

    def test_quantiles_must_increase(self):
        from eeai.model import metalog
        with self.assertRaises(ValueError):
            metalog.Fit(np.array([[1, 1, 2, 3, 4]]), np.array([0]))


@needs_numpy
class TestIdentities(unittest.TestCase):
    def _world(self, Q2, P2=(1.0, 1.0)):
        """Two industries, one year (2026), one occupation; every other input neutral."""
        W, T, I_, O = 1, 1, 2, 1
        one = lambda *shape: np.ones(shape)
        base = {"N0": np.array([[60.0, 40.0]]), "H0": np.array([[100.0, 100.0]]), "E0": np.array([[0.05, 0.05]]),
                "lambda0": np.full((W, I_), 0.6), "sigma0": one(W, I_, O), "u0": np.full((W, O), 0.05),
                "n0": np.array([0.01]), "Pop0": np.array([0.2]), "omega0": one(W, O), "p10_0": np.array([500.0]),
                "p50_0": np.array([1000.0]), "p90_0": np.array([2500.0]), "ECI0": one(W), "C0": one(W),
                "sA0": np.full((W, O), 0.1), "sM0": np.full((W, O), 0.0), "rA0": np.full((W, O), 0.5), "rM0": np.full((W, O), 0.2)}
        fut = {"Q": np.array([[Q2]]), "P": np.array([[P2]]), "pi": one(W, T, I_), "h": np.full((W, T, I_), 2000.0),
               "K": one(W, T, I_), "lambda": np.full((W, T, I_), 0.6), "sigma": one(W, T, I_, O), "u": np.full((W, T, O), 0.05),
               "n": np.full((W, T), 0.01), "Pop": np.full((W, T), 0.2), "omega": one(W, T, O), "p10": np.full((W, T), 500.0),
               "p50": np.full((W, T), 1000.0), "p90": np.full((W, T), 2500.0), "ECI": one(W, T), "C": one(W, T),
               "sA": np.full((W, T, O), 0.1), "sM": np.full((W, T, O), 0.0), "rA": np.full((W, T, O), 0.5), "rM": np.full((W, T, O), 0.2)}
        return base, fut

    def test_the_fisher_chain_against_a_hand_computation(self):
        from eeai.model import identities
        base, fut = self._world((1.10, 1.00), (0.80, 1.00))
        out, _ = identities.compute(base, fut, [1])
        # Weights 0.6/0.4 in 2025; in 2026 nominal 60*1.1*0.8 = 52.8 and 40, so 0.569/0.431.
        lasp = 0.6 * 1.10 + 0.4 * 1.00
        w1 = np.array([52.8, 40.0]) / 92.8
        paas = 1 / (w1[0] / 1.10 + w1[1] / 1.00)
        self.assertAlmostEqual(out["gdp_growth"][0, 1], (np.sqrt(lasp * paas) - 1) * 100, places=10)
        self.assertTrue(np.isnan(out["gdp_growth"][0, 0]))
        # Contributions (growth x average share) add up to the total approximately: here, with a 20%
        # price fall, to within 0.15 points of 5.73%.
        self.assertLess(abs(np.nansum(out["sector_contribution"][0, 1]) - out["gdp_growth"][0, 1]), 0.15)

    def test_real_pay_splits_exactly_into_its_three_factors(self):
        from eeai.model import identities
        base, fut = self._world((1.07, 1.02), (1.05, 0.98))
        fut["lambda"] = np.array([[[0.55, 0.62]]])
        fut["pi"] = np.array([[[1.03, 1.01]]])
        fut["C"] = np.array([[1.03]])
        out, _ = identities.compute(base, fut, [1])
        lhs = out["real_pay_index"][0, 1]
        rhs = out["real_pay_lp"][0, 1] * out["real_pay_labor_share"][0, 1] * out["real_pay_price_gap"][0, 1]
        self.assertAlmostEqual(lhs, rhs, places=12)

    def test_growth_over_a_long_gap_is_the_average_annual_rate(self):
        from eeai.model import identities
        base, fut = self._world((1.0, 1.0))
        fut = {k: np.concatenate([v, v], axis=1) for k, v in fut.items()}
        fut["Q"][0, 1] = 1.0 * 1.02 ** 5                     # 2035: five years of 2% from 2030
        out, _ = identities.compute(base, fut, [1, 5])
        self.assertAlmostEqual(out["gdp_growth"][0, 2], 2.0, places=8)

    def test_the_2025_identities_reproduce_the_placeholder_totals(self):
        from eeai.model import simulate
        spec = M.load()
        record = synthetic.placeholder_record(spec)
        rows = run.ask(MEMBERS[0], spec, record, TODAY, "x", harness_run=synthetic.harness_run(spec, record, TODAY), synthetic=True)
        _, diag = simulate.simulate_system(spec, rows, 200, np.random.default_rng(0), np)
        official = {k.removeprefix("official."): v["value"] for k, v in record.items() if k.startswith("official.")}
        for k, v in diag["baseline_totals"].items():
            self.assertAlmostEqual(v, official[k], delta=abs(official[k]) * 1e-6, msg=k)


@needs_numpy
class TestSimulationAndPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        spec = M.load()
        record = synthetic.placeholder_record(spec)
        (cls.dir / "runs").mkdir()
        cls.run_file = cls.dir / "runs" / "2026-11-18T0000Z.jsonl"
        panel = {"members": [{"label": m["label"]} for m in MEMBERS]}
        with open(cls.run_file, "w", encoding="utf-8") as f:
            for m in reversed(MEMBERS):                         # rows land in the order calls finish
                for r in run.ask(m, spec, record, TODAY, cls.run_file.stem, panel=panel,
                                 harness_run=synthetic.harness_run(spec, record, TODAY), synthetic=True):
                    f.write(json.dumps(r) + "\n")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_simulation_is_reproducible_and_complete(self):
        from eeai.model import simulate
        a = simulate.run(self.run_file, worlds=300, seed=7)
        b = simulate.run(self.run_file, worlds=300, seed=7)
        self.assertEqual(json.dumps(a), json.dumps(b))
        self.assertEqual(a["systems"], ["Model A", "Model B"])      # panel order, not finish order
        self.assertEqual(set(a["summaries"]), {"Model A", "Model B", "ensemble"})
        self.assertEqual(set(a["summaries"]["ensemble"]), {"unconditional", "slow", "moderate", "rapid"})
        gdp = a["summaries"]["ensemble"]["unconditional"]["gdp_growth"]
        self.assertEqual(len(gdp), 10)                               # 2025, then the nine years asked
        self.assertEqual(gdp[0], [None] * 5)
        self.assertTrue(all(c[0] <= c[2] <= c[4] for c in gdp[1:]))
        self.assertEqual(len(a["summaries"]["Model A"]["rapid"]["sector_growth"]), 22)
        self.assertTrue(a["synthetic"])

    def test_an_incomplete_model_is_skipped_and_named(self):
        from eeai.model import simulate
        rows = [json.loads(line) for line in self.run_file.read_text().splitlines()]
        for r in rows:
            if r["label"] == "Model B" and r["question_id"] == "Q.retail":
                r["forecasts"] = {}
        broken = self.dir / "broken.jsonl"
        broken.write_text("".join(json.dumps(r) + "\n" for r in rows))
        blob = simulate.run(broken, worlds=100)
        self.assertEqual(blob["systems"], ["Model A"])
        self.assertIn("Model B", blob["skipped"])

    def test_the_site_holds_both_pages(self):
        from eeai import build
        from eeai.model import simulate
        sims = self.dir / "sims"
        sims.mkdir(exist_ok=True)
        blob = simulate.run(self.run_file, worlds=200)
        (sims / f"{blob['run_id']}.json").write_text(json.dumps(blob))
        site = self.dir / "site"
        args = SimpleNamespace(runs=str(self.dir / "no-survey-runs"), out=None, site=str(site), json=None,
                               model_sims=str(sims), model_runs=str(self.dir / "runs"))
        build.main(args)
        index, model = (site / "index.html").read_text(), (site / "model.html").read_text()
        self.assertIn('href: "model.html"', (config.PAGE_DIR / "20-app.js").read_text())      # the survey links to the model
        self.assertIn("<!--EEAI_DATA-->", index)
        self.assertIn("<!--EEAI_MODEL_DATA-->", model)
        self.assertNotIn("EEAI_MODEL_DATA", index)
        from dashboard import page as kit
        data = json.loads(kit.blocks(model.encode())["EEAI_MODEL_DATA"].split(b"= ", 1)[1].rsplit(b";</script>", 1)[0])
        self.assertEqual(data["latest"]["models"], ["Model A", "Model B"])
        self.assertTrue(data["synthetic"])
        with zipfile.ZipFile(site / mbuild.NAME) as z:
            names = z.namelist()
        self.assertIn("quantiles.csv", names)
        self.assertIn("runs/2026-11-18T0000Z.jsonl", names)
        # The detail cards' data beside the page: the inputs (2025 first) and the intermediate totals, not the outcomes.
        # The History view: each run's ensemble headline forecasts, with that run's years.
        self.assertEqual([r["run_id"] for r in data["history"]], ["2026-11-18T0000Z"])
        self.assertEqual(data["history"][0]["years"], data["years"])
        self.assertEqual(set(data["history"][0]["cells"]["moderate"]), {h[0] for h in mbuild.HEADLINE})
        self.assertEqual(data["inputs"], mbuild.INPUTS)
        inputs = json.loads((site / mbuild.INPUTS).read_text())
        moderate = inputs["ensemble"]["moderate"]
        self.assertEqual(len(moderate["in.Q"]), len(data["industries"]))                   # one row per industry
        self.assertEqual(len(moderate["in.Q"][0]), len(data["years"]))                     # then per year, 2025 first
        self.assertEqual(moderate["in.Q"][0][0][2], 1.0)                                  # an index, 2025 = 1
        self.assertIn("labor_force", moderate)
        self.assertNotIn("gdp_growth", moderate)
        self.assertIn("unconditional", inputs["Model A"])

    def test_a_publication_refuses_synthetic_or_incomplete_model_summaries(self):
        from eeai.model import simulate
        blob = simulate.run(self.run_file, worlds=50)
        sims = self.dir / "pub-sims"
        sims.mkdir(exist_ok=True)
        (sims / f"{blob['run_id']}.json").write_text(json.dumps(blob))
        with self.assertRaisesRegex(ValueError, "synthetic"):
            mbuild.write(self.dir / "pub-site", sims, publication=True)
        (sims / f"{blob['run_id']}.json").write_text(json.dumps({**blob, "synthetic": False, "skipped": {"Model B": "incomplete"}}))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            mbuild.write(self.dir / "pub-site", sims, publication=True)
        (sims / f"{blob['run_id']}.json").write_text(json.dumps({**blob, "synthetic": False}))
        self.assertEqual(mbuild.write(self.dir / "pub-site", sims, publication=True)["latest"]["models"], ["Model A", "Model B"])
        mbuild.write(self.dir / "preview-site", sims)                    # (a preview build takes anything)

    def test_a_synthetic_run_is_never_simulated_into_results(self):
        from eeai.model import simulate
        with self.assertRaises(SystemExit):
            simulate.main(SimpleNamespace(run_file=str(self.run_file), out=None, worlds=10, seed=1))

    def test_the_detail_cards_name_only_series_the_simulation_has(self):
        import re
        from eeai.model import simulate
        blob = simulate.run(self.run_file, worlds=50)
        have = set(blob["summaries"]["ensemble"]["moderate"])
        src = (config.MODEL_PAGE_DIR / "25-recipes.js").read_text()
        recipes = src.split("const RECIPES = {", 1)[1].split("\nconst MEASURES", 1)[0]
        recipes = re.sub(r'GROWTH\("[^"]*"\)', "", recipes)                             # (an equation's symbol, not a series)
        named = set(re.findall(r'"((?:in\.)?[A-Za-z_0-9]+)"', recipes)) - {"sigma"}   # (the occupation mix is not listed)
        self.assertEqual(named - have, set())
        series = set(re.findall(r'^  "?([A-Za-z_.0-9]+)"?: \{', src.split("const SERIES = {", 1)[1].split("\n};", 1)[0], re.M))
        self.assertEqual(named - series, set(), "every series a card names has a label and unit")
        cards = set(re.findall(r"^  (\w+): \{", recipes, re.M))
        self.assertEqual(cards, {h[0] for h in mbuild.HEADLINE})
        # What the page does not carry, the inputs file must.
        page = {h[0] for h in mbuild.HEADLINE} | {d[0] for d in mbuild.DECOMPOSITION} | {x[0] for x in mbuild.SECTOR} | {x[0] for x in mbuild.OCCUPATION}
        self.assertEqual({n for n in named - page if not n.startswith("in.")} - set(mbuild.INTERMEDIATE), set())

    def test_the_model_page_without_a_simulation_says_so(self):
        blob = mbuild.build([])
        self.assertIsNone(blob["latest"])
        self.assertIn("No forecasts yet", (config.MODEL_PAGE_DIR / "30-app.js").read_text())
        self.assertIn("<!--EEAI_MODEL_DATA-->", mbuild.page(blob))


if __name__ == "__main__":
    unittest.main()
