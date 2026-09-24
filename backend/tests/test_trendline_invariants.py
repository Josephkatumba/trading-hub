"""Trendline baseline: rules that must hold for ANY input, not just the fixtures.

These pin the semantics the multi-strategy work must preserve: what counts as
a confirmed trendline setup, that directional context never becomes a setup
with levels, and how break/reversal families map to trendline geometry.
"""
from __future__ import annotations

import sys
from pathlib import Path

import random
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g  # noqa: F401  (puts backend on sys.path)
from scanner import analyze_symbol

BREAKDOWN_KEYS = {"trendline", "structure", "support_resistance", "price_action", "session", "momentum", "higher_timeframe", "crt"}
GEOMETRY = {("BREAK", "LONG"): "DESCENDING_RESISTANCE", ("REVERSAL", "SHORT"): "DESCENDING_RESISTANCE",
            ("BREAK", "SHORT"): "ASCENDING_SUPPORT", ("REVERSAL", "LONG"): "ASCENDING_SUPPORT"}


def walk(seed: int, count: int, step: float, vol: float) -> list[dict]:
    rng, price, rows, drift = random.Random(seed), 100.0, [], 0.0
    for i in range(count):
        if i % rng.randint(10, 28) == 0:
            drift = rng.uniform(-0.7, 0.7) * vol
        close = price + drift + rng.gauss(0, vol)
        rows.append({"time": 1790000000.0 + i * step, "open": price, "high": max(price, close) + abs(rng.gauss(0, vol * 0.6)),
                     "low": min(price, close) - abs(rng.gauss(0, vol * 0.6)), "close": close})
        price = close
    return rows


def results(samples: int = 500):
    sessions = [None, {"session": "London"}, {"session": "New York", "session_alignment": "aligned"}]
    for seed in range(samples):
        yield seed, analyze_symbol("SYN", walk(seed, 130, 900.0, 0.3 + (seed % 5) * 0.1), spread=0.01,
                                   session_context=sessions[seed % 3], higher_rows=walk(seed + 10**6, 80, 3600.0, 0.7))


class TrendlineInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = list(results())

    def test_sample_reaches_confirmed_developing_and_context_states(self):
        states = {(r["state"], bool(r.get("strategy_valid"))) for _, r in self.results}
        self.assertTrue({("CONFIRMING", True), ("DEVELOPING", False), ("WATCHING", False)} <= states, states)

    def test_confirmation_requires_every_trendline_gate(self):
        for seed, r in self.results:
            if r["strategy_valid"]:
                with self.subTest(seed=seed):
                    self.assertEqual(r["state"], "CONFIRMING")
                    self.assertTrue(r["trendline_gate"])
                    self.assertTrue(r["confirmation_alignment"])
                    self.assertGreaterEqual(r["rr"], 1.5)
                    self.assertIsNotNone(r["stop_loss"])
                    self.assertIsNotNone(r["take_profit"])

    def test_no_strategy_state_without_a_trendline_event(self):
        for seed, r in self.results:
            if r["state"] in {"CONFIRMING", "DEVELOPING"}:
                with self.subTest(seed=seed):
                    self.assertTrue(r["trendline_gate"])
                    self.assertIn(r["setup_family"], {"BREAK", "REVERSAL"})

    def test_directional_context_is_never_a_setup_with_levels(self):
        seen = 0
        for seed, r in self.results:
            if r["state"] == "WATCHING" and not r["trendline_gate"]:
                seen += 1
                with self.subTest(seed=seed):
                    self.assertEqual(r["setup"], "Directional context only")
                    self.assertIsNone(r["setup_family"])
                    for key in ("stop_loss", "take_profit", "risk_distance", "reward_distance", "rr"):
                        self.assertIsNone(r[key], key)
                    self.assertFalse(r["strategy_valid"])
        self.assertGreater(seen, 0)

    def test_family_direction_matches_trendline_geometry(self):
        for seed, r in self.results:
            if r["setup_family"]:
                with self.subTest(seed=seed):
                    self.assertEqual(r["trendline_identity"]["orientation"], GEOMETRY[(r["setup_family"], r["direction"])])
                    self.assertEqual(len(r["trendline_identity"]["anchors"]), 2)

    def test_score_is_the_capped_sum_of_a_fixed_breakdown(self):
        for seed, r in self.results:
            with self.subTest(seed=seed):
                self.assertEqual(set(r["score_breakdown"]), BREAKDOWN_KEYS)
                self.assertEqual(r["score"], min(sum(r["score_breakdown"].values()), 100))

    def test_strategy_identity_fields_are_stable(self):
        for _, r in self.results:
            self.assertEqual((r["strategy_version"], r["timeframe"], r["higher_timeframes"]), ("trendline-first-v3", "M15", ["H1"]))

    def test_insufficient_history_is_no_setup(self):
        r = analyze_symbol("SYN", walk(1, 59, 900.0, 0.3))
        self.assertEqual((r["state"], r["setup"], r["score"]), ("NO SETUP", "Insufficient data", 0))


if __name__ == "__main__":
    unittest.main()
