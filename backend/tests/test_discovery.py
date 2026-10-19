"""T-033: strategy library, discovery workflow guards, qualification registry and integration adapter."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research import discovery, library

REQUIRED = ("key", "name", "category", "source", "source_type", "rationale", "rules", "timeframes", "data",
            "evidence", "caveats")


class LibraryTests(unittest.TestCase):
    def test_entries_are_documented_and_unique(self):
        keys = [e["key"] for e in library.LIBRARY]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertGreaterEqual(len(keys), 25)
        for e in library.LIBRARY:
            for field in REQUIRED:
                self.assertIn(field, e, f"{e['key']} lacks {field}")
        self.assertGreaterEqual(len({e["category"] for e in library.LIBRARY}), 10)

    def test_unavailable_data_is_rejected_at_intake(self):
        self.assertFalse(library.available(library.get("fx_carry"))[0])
        self.assertIn("swap_history", library.available(library.get("fx_carry"))[1])
        self.assertFalse(library.available(library.get("pairs"))[0])          # blocked infrastructure
        self.assertTrue(library.available(library.get("rsi2"))[0])

    def test_search_and_export(self):
        self.assertIn("intraday_momentum", [e["key"] for e in library.search("Gao")])
        with tempfile.TemporaryDirectory() as temp:
            path = library.export_markdown(Path(temp) / "lib.md")
            text = path.read_text(encoding="utf-8")
            self.assertIn("Breedon & Ranaldo", text)
            self.assertIn("data unavailable", text)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.path = Path(self._temp.name) / "registry.json"
        self.patches = [mock.patch.object(discovery, "registry_path", lambda: self.path),
                        mock.patch.object(discovery.lab, "record", lambda entry: None),
                        mock.patch.object(discovery, "fingerprint", lambda key, configs: "fp-" + key)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self._temp.cleanup()

    def _fake_selection(self, chosen="cfg", positive=True):
        return {"train": {"cfg": {}}, "shortlist": ["cfg"], "validation": {"cfg": {"expectancy_r": 0.1, "trades": 40}},
                "chosen": chosen, "chosen_validation_positive": positive, "_signals": {"cfg": []}}

    def _scored(self, e=0.05):
        test = {"trades": 100, "expectancy_r": e, "expectancy_ci95": [-0.1, 0.2], "profit_factor": 1.1}
        return {"config": "cfg", "test": test, "test_x2_costs": test, "development_x2_costs": test,
                "positive_folds": "3/6", "_test_trades": [{"r": 0.1}] * 40 + [{"r": -0.05}] * 60}

    def test_test_window_is_consumed_once_and_dedupe_skips_rework(self):
        reg = discovery.load()
        spec = {"grid": {"cfg": lambda: []}}
        with mock.patch.object(discovery.v6, "select", return_value=self._fake_selection()), \
             mock.patch.object(discovery.v6, "score_test", return_value=self._scored()) as scored, \
             mock.patch.object(discovery, "random_percentile", return_value={}), \
             mock.patch.object(discovery.library, "get", return_value={"rationale": "r"}):
            discovery.evaluate(reg, "demo", spec, lambda m: None)
            self.assertEqual(scored.call_count, 1)
            self.assertEqual(reg["strategies"]["demo"]["status"], "BACKTESTED")          # promising, not proven
            self.assertIn("demo::cfg", reg["test_consumed"])
            discovery.evaluate(reg, "demo", spec, lambda m: None)                       # same fingerprint
            self.assertEqual(scored.call_count, 1)
            reg["strategies"]["demo"]["fingerprint"] = "changed"                         # new grid/data, same config
            with self.assertRaises(RuntimeError):
                discovery.evaluate(reg, "demo", spec, lambda m: None)
            self.assertEqual(scored.call_count, 1)

    def test_rejections_are_archived(self):
        reg = discovery.load()
        with mock.patch.object(discovery.v6, "select", return_value=self._fake_selection(positive=False)), \
             mock.patch.object(discovery.library, "get", return_value={"rationale": "r"}):
            discovery.evaluate(reg, "weak", {"grid": {"cfg": lambda: []}}, lambda m: None)
        self.assertEqual(reg["strategies"]["weak"]["status"], "ARCHIVED")
        self.assertEqual(reg["strategies"]["weak"]["result"]["verdict"], "REJECTED ON VALIDATION")

    def test_promotion_needs_approval_and_order(self):
        reg = discovery.load()
        discovery.set_status(reg, "cand", "BACKTESTED", "promising")
        discovery.save(reg)
        with self.assertRaises(SystemExit):
            discovery.promote("cand", "FORWARD_TESTING", "")
        with self.assertRaises(SystemExit):
            discovery.promote("cand", "PRODUCTION_CANDIDATE", "CEO 2026-10-20")    # must forward-test first
        discovery.promote("cand", "FORWARD_TESTING", "CEO 2026-10-20")
        self.assertEqual(discovery.load()["strategies"]["cand"]["status"], "FORWARD_TESTING")


class AdapterTests(unittest.TestCase):
    def test_adapter_matches_research_rule_and_is_not_registered(self):
        from research import v6
        from research.adapter import ReversionShadowStrategy
        from strategies import REGISTRY
        try:
            from test_research_lab import history, synthetic
        except ImportError:
            from tests.test_research_lab import history, synthetic
        self.assertNotIn("reversion_v6_r1", REGISTRY.enabled())
        h = history(synthetic(n_m15=240 * 96, seed=21))
        v6._H1.pop(h.symbol, None)
        research = {s["index"]: s for s in v6.bollinger_reversion(h, 2.5, "mean")}
        strat = ReversionShadowStrategy()
        fired = {}
        h1_open = {b["utc"] + 3600 for b in h.full["H1"]}
        for i in range(400, len(h.full["M15"]) - 1):
            if h.full["M15"][i]["utc"] not in h1_open:
                continue
            built = h.market_input(i)
            if built:
                p = strat.evaluate(built[0])
                if p["strategy_valid"]:
                    fired[i] = p
        self.assertTrue(research, "fixture produced no research signals")
        common = [i for i in research if i in fired]
        checked = [i for i in research if h.market_input(i)]
        self.assertEqual(set(fired), set(checked))                      # no misses, no false positives
        for i in common:
            self.assertEqual(fired[i]["direction"], research[i]["direction"])
            self.assertAlmostEqual(fired[i]["stop_loss"], research[i]["stop_loss"], places=6)
            self.assertAlmostEqual(fired[i]["take_profit"], research[i]["take_profit"], places=6)


if __name__ == "__main__":
    unittest.main()
