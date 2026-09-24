"""Trendline baseline: what record_markets writes is frozen, end to end.

Real and synthetic scanner outputs are fed through three scan rounds (open,
continue, replace) with pinned time and UUIDs. The resulting observation,
lifecycle and confirmation files must match tests/fixtures/golden/persistence
byte for byte, and the frozen pre-index implementation must agree.

Phase 3 intentionally ADDED strategy metadata (golden_support.STRATEGY_RECORD_FIELDS)
and the golden files were regenerated once for it; with those fields removed they
are byte-identical to the Phase 0 goldens, and the frozen pre-strategy
implementation must still agree on everything else.

Phase 9 correction (trendline-first-v4): the goldens above stay the v3 baseline,
reproduced by running the current code with the v3 strategy. v4 has its own
goldens (tests/fixtures/golden/persistence_trendline-first-v4); the fixture
rounds carry their own session context, so v4's records differ from v3's only in
the strategy_version label (asserted below, not assumed).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g

import legacy_observations  # noqa: E402
import observations  # noqa: E402


class PersistenceGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.current = g.run_persistence(observations, Path(cls.tmp.name) / "current", legacy=True)   # trendline-first-v3
        cls.v4 = g.run_persistence(observations, Path(cls.tmp.name) / "v4")                            # registered version
        cls.legacy = g.run_persistence(legacy_observations, Path(cls.tmp.name) / "legacy")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_records_match_the_golden_files_byte_for_byte(self):
        for name in g.PERSISTED_FILES:
            with self.subTest(file=name):
                expected = (g.PERSISTENCE_GOLDEN / name).read_bytes()
                if self.current[name] != expected:
                    new = self.current[name].splitlines(); old = expected.splitlines()
                    first = next((i for i, (a, b) in enumerate(zip(new, old)) if a != b), min(len(new), len(old)))
                    self.fail(f"{name} changed: {len(old)} -> {len(new)} records, first difference at record {first}")

    def test_v4_records_match_the_v4_golden_files_byte_for_byte(self):
        for name in g.PERSISTED_FILES:
            with self.subTest(file=name):
                self.assertEqual(self.v4[name], (g.PERSISTENCE_GOLDEN_V4 / name).read_bytes())

    def test_v4_differs_from_the_v3_baseline_only_in_the_version_label(self):
        for name in g.PERSISTED_FILES:
            old, new = self.current[name].splitlines(keepends=True), self.v4[name].splitlines(keepends=True)
            with self.subTest(file=name):
                self.assertEqual(len(old), len(new))
                self.assertEqual(new, [line.replace(b'"strategy_version":"trendline-first-v3"', b'"strategy_version":"trendline-first-v4"')
                                       for line in old])
                labelled = [json.loads(line) for line in new if b'"strategy_version"' in line]
                self.assertEqual({r["strategy_version"] for r in labelled}, set() if name == "setup_lifecycle.jsonl" else {g.TRENDLINE_V4})
                self.assertEqual(len(labelled), len(new) if name != "setup_lifecycle.jsonl" else 0)

    def test_frozen_pre_index_implementation_agrees(self):
        # Identical except for the strategy fields, which carry only trendline values.
        for name in g.PERSISTED_FILES:
            with self.subTest(file=name):
                self.assertEqual(g.without_strategy_bytes(self.current[name]), self.legacy[name])

    def test_strategy_fields_are_the_only_additions_and_are_trendline(self):
        snapshots = [json.loads(line) for line in self.current["setup_observations.jsonl"].splitlines()]
        confirmations = [json.loads(line) for line in self.current["setup_confirmations.jsonl"].splitlines()]
        self.assertTrue(g.only_trendline_fields(g.jsonl_strategy_fields(self.current["setup_observations.jsonl"])))
        self.assertEqual({s["strategy_id"] for s in snapshots}, {"trendline"})
        self.assertEqual({s["strategy_version"] for s in snapshots}, {g.TRENDLINE_V3})
        self.assertEqual({s["episode_identity"]["strategy_id"] for s in snapshots}, {"trendline"})
        self.assertEqual({c["strategy_id"] for c in confirmations}, {"trendline"})
        self.assertEqual(g.jsonl_strategy_fields(self.current["setup_lifecycle.jsonl"]), [])

    def test_golden_run_exercises_the_trendline_lifecycle(self):
        events = [json.loads(line) for line in self.current["setup_lifecycle.jsonl"].splitlines()]
        transitions = {(e["to_state"], e["reason_code"]) for e in events}
        for expected in [("DETECTED", "FIRST_DETECTION"), ("CONFIRMED", "FIRST_DETECTION"), ("ACTIVE", "SCANNER_STATE_CHANGED"),
                         ("INVALIDATED", "DIRECTION_CHANGED"), ("INVALIDATED", "INVALIDATION_PRICE_CROSSED")]:
            self.assertIn(expected, transitions)
        self.assertGreater(len(self.current["setup_confirmations.jsonl"].splitlines()), 0)

    def test_every_confirmation_comes_from_a_strategy_valid_trendline_snapshot(self):
        snapshots = {s["observation_id"]: s for s in map(json.loads, self.current["setup_observations.jsonl"].splitlines())}
        for confirmation in map(json.loads, self.current["setup_confirmations.jsonl"].splitlines()):
            snapshot = snapshots[confirmation["observation_id"]]
            self.assertTrue(snapshot["rule_evidence"]["strategy_valid"])
            self.assertTrue(snapshot["rule_evidence"]["trendline_gate"])
            self.assertIn(snapshot["setup_type"], {"BREAK", "REVERSAL"})
            self.assertEqual(confirmation["strategy_version"], g.TRENDLINE_V3)

    def test_context_episodes_never_confirm_and_carry_no_levels(self):
        snapshots = list(map(json.loads, self.current["setup_observations.jsonl"].splitlines()))
        confirmed = {json.loads(c)["setup_id"] for c in self.current["setup_confirmations.jsonl"].splitlines()}
        context = [s for s in snapshots if s["setup_type"] == "WATCHING"]
        self.assertGreater(len(context), 0)
        for snapshot in context:
            self.assertNotIn(snapshot["setup_id"], confirmed)
            self.assertIsNone(snapshot["proposed_stop_loss"])
            self.assertIsNone(snapshot["proposed_take_profit"])
            self.assertFalse(snapshot["rule_evidence"]["strategy_valid"])


if __name__ == "__main__":
    unittest.main()
