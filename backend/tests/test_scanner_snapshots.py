"""Trendline baseline: scanner.analyze_symbol output is frozen.

Every fixture in tests/fixtures/scanner (10 real MT5 captures of the official
scan instruments + synthetic series chosen to reach each branch) must produce
exactly the output stored in tests/fixtures/golden/scanner_golden.json.
A failure here means trendline behaviour changed. Regenerate the golden file
only for an approved change (tests/tools/regen_golden.py) and review the diff.
"""
from __future__ import annotations

import sys
from pathlib import Path

import copy
import json
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g
import scanner

REQUIRED_BRANCHES = {
    "CONFIRMING|BREAK|LONG|valid", "CONFIRMING|BREAK|SHORT|valid",
    "CONFIRMING|REVERSAL|LONG|valid", "CONFIRMING|REVERSAL|SHORT|valid",
    "CONFIRMING|*|*|notvalid", "DEVELOPING|BREAK|*|*", "DEVELOPING|REVERSAL|*|*",
    "WATCHING|none|*|*", "NO SETUP|none|*|*", "insufficient",
}


def branch_of(result: dict) -> str:
    valid = "valid" if result.get("strategy_valid") else "notvalid"
    return f"{result['state']}|{result.get('setup_family') or 'none'}|{result.get('direction')}|{valid}"


class ScannerSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = g.load_fixtures()
        cls.golden = json.loads(g.SCANNER_GOLDEN.read_text(encoding="utf-8"))

    def test_every_fixture_matches_its_frozen_output(self):
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture["name"]):
                actual = json.loads(g.canonical(g.scan(fixture)))
                expected = self.golden[fixture["name"]]
                changed = sorted(key for key in set(actual) | set(expected) if actual.get(key, "<missing>") != expected.get(key, "<missing>"))
                self.assertEqual(actual, expected, "trendline output changed in fields: " + ", ".join(changed))

    def test_golden_and_fixtures_correspond_one_to_one(self):
        self.assertEqual(sorted(self.golden), sorted(f["name"] for f in self.fixtures))

    def test_real_captures_cover_the_official_scan_instruments(self):
        real = {f["symbol"] for f in self.fixtures if f["name"].startswith("real_")}
        self.assertEqual(real, set(g.OFFICIAL_SCAN))
        for fixture in self.fixtures:
            if fixture["name"].startswith("real_"):
                self.assertEqual((len(fixture["rows"]), len(fixture["higher_rows"])), (300, 160), fixture["name"])

    def test_fixture_set_still_reaches_every_reachable_branch(self):
        reached = set()
        for fixture in self.fixtures:
            result = self.golden[fixture["name"]]
            key = "insufficient" if result.get("setup") == "Insufficient data" else branch_of(result)
            for required in REQUIRED_BRANCHES:
                parts = required.split("|")
                if required == key or (len(parts) == 4 and all(p == "*" or p == k for p, k in zip(parts, key.split("|")))):
                    reached.add(required)
        self.assertEqual(REQUIRED_BRANCHES - reached, set())

    def test_scan_is_deterministic_and_does_not_mutate_inputs(self):
        for fixture in self.fixtures[:6]:
            before = copy.deepcopy(fixture)
            first, second = g.canonical(g.scan(fixture)), g.canonical(g.scan(fixture))
            self.assertEqual(first, second)
            self.assertEqual(fixture, before)

    def test_trendline_watch_branch_keeps_levels_but_is_never_valid(self):
        # A trendline event scoring < 50 never occurred in ~18.5k real snapshots,
        # so it is forced here through the real analyze_symbol path.
        fixture = next(f for f in self.fixtures if f["name"] == "real_EURUSD")
        rows = fixture["rows"]
        with mock.patch.object(scanner, "_trendline_signal", return_value={
                "family": "BREAK", "direction": "LONG", "line": float(rows[-1]["close"]),
                "label": "Trendline resistance break", "identity": {"orientation": "DESCENDING_RESISTANCE", "anchors": []}}), \
             mock.patch.object(scanner, "_price_action", return_value={"state": "NEUTRAL", "label": "Neutral price action", "direction": None}), \
             mock.patch.object(scanner, "_crt_context", return_value={"state": "RANGE", "label": "Range", "direction": None}), \
             mock.patch.object(scanner, "_nearest_level", return_value=(0.0, 99.0, "NONE")), \
             mock.patch.object(scanner, "_structure_label", return_value="Mixed / range"), \
             mock.patch.object(scanner, "_htf_bias", return_value="BEARISH"):
            result = scanner.analyze_symbol("EURUSD", rows, higher_rows=fixture["higher_rows"])
        self.assertLess(result["score"], 50)
        self.assertEqual((result["state"], result["setup"]), ("WATCHING", "Trendline break watch"))
        self.assertTrue(result["trendline_gate"])
        self.assertIsNotNone(result["stop_loss"], "a trendline watch keeps its levels (only context watches drop them)")
        self.assertFalse(result["strategy_valid"])


if __name__ == "__main__":
    unittest.main()
