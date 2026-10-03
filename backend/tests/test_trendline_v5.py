"""trendline-first-v5 (experimental, not registered): closed bars only + H1 structural targets.

1-4  the forming M15 / H1 bar and the live price cannot create, reverse or confirm a
     setup, alter the H1 bias or the session context (v4 is shown to be affected on
     the same inputs, so each test is meaningful);
5-8  the target is the nearest H1 structural swing ahead of entry, never jumped,
     never from future bars, and the 1.5R gate decides (below rejects, above can pass);
9-10 v4 is still the registered live trendline and its output is unchanged.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support  # noqa: F401,E402  (puts backend on sys.path)

import scanner  # noqa: E402
from session_time import compute_session_context, corrected_bar_time  # noqa: E402
from strategies import TRENDLINE, build_default_registry  # noqa: E402
from strategies.base import MarketInput  # noqa: E402
from strategies.trendline import TrendlineStrategy, TrendlineV5Strategy, closed_bars  # noqa: E402
from v5_fixtures import BASIS, forming_variants, h1_rows, m15_rows  # noqa: E402

V4, V5 = TrendlineStrategy(), TrendlineV5Strategy(basis=BASIS)
SEEDS = range(40)


def market(rows, h1):
    return MarketInput("XAUUSD", rows, spread=0.02, higher_rows=h1)


def case(seed):
    full = m15_rows(seed)
    closed = full[:-1]
    return closed, h1_rows(full), scanner._atr(closed)


def v5_scan(seed):
    """v5 as a live scan sees the market: closed history plus a (flat) forming bar."""
    closed, h1, atr = case(seed)
    return V5.evaluate(market(closed + [forming_variants(closed[-1], atr)["flat"]], h1))


class FormingBarTests(unittest.TestCase):
    def test_v5_ignores_every_possible_forming_m15_bar(self):
        for seed in SEEDS:
            closed, h1, atr = case(seed)
            results = {name: V5.evaluate(market(closed + [bar], h1)) for name, bar in forming_variants(closed[-1], atr).items()}
            baseline = results.pop("flat")
            for name, result in results.items():
                with self.subTest(seed=seed, forming=name):
                    self.assertEqual(result, baseline)

    def test_forming_m15_bar_cannot_create_a_confirmation(self):
        # Seed 2: a forming rejection wick turns v4 CONFIRMING; v5 is unmoved.
        closed, h1, atr = case(2)
        variants = forming_variants(closed[-1], atr)
        v4_flat, v4_wick = (V4.evaluate(market(closed + [variants[k]], h1)) for k in ("flat", "wick_up_reject"))
        self.assertNotEqual(v4_flat["state"], "CONFIRMING")
        self.assertEqual(v4_wick["state"], "CONFIRMING", "fixture must show the v4 repaint")
        v5_flat, v5_wick = (V5.evaluate(market(closed + [variants[k]], h1)) for k in ("flat", "wick_up_reject"))
        self.assertEqual(v5_wick, v5_flat)
        self.assertFalse(v5_wick["strategy_valid"] and not v5_flat["strategy_valid"])

    def test_forming_m15_bar_cannot_reverse_the_direction(self):
        # Seed 1: a forming crash flips v4's direction (the DIRECTION_CHANGED churn); v5 keeps it.
        closed, h1, atr = case(1)
        variants = forming_variants(closed[-1], atr)
        v4_flat, v4_crash = (V4.evaluate(market(closed + [variants[k]], h1)) for k in ("flat", "crash_down"))
        self.assertNotEqual(v4_flat["direction"], v4_crash["direction"], "fixture must show the v4 flip")
        self.assertEqual(V5.evaluate(market(closed + [variants["crash_down"]], h1))["direction"],
                         V5.evaluate(market(closed + [variants["flat"]], h1))["direction"])

    def test_forming_h1_bar_cannot_alter_the_h1_bias(self):
        # Seed 2: an extreme forming H1 bar flips v4's H1 bias; v5 reads closed H1 bars only.
        full = m15_rows(2)
        h1 = h1_rows(full)
        extreme = h1[:-1] + [{**h1[-1], "high": h1[-1]["high"] + 50, "close": h1[-1]["close"] + 40}]
        self.assertNotEqual(V4.evaluate(market(full, h1))["higher_timeframe_bias"], V4.evaluate(market(full, extreme))["higher_timeframe_bias"])
        self.assertEqual(V5.evaluate(market(full, h1)), V5.evaluate(market(full, extreme)))

    def test_v5_is_exactly_the_trendline_rules_on_closed_bars(self):
        closed, h1, _ = case(7)
        context = V5.closed_session_context(closed, BASIS)
        expected = scanner.analyze_symbol("XAUUSD", closed, spread=0.02, session_context=context, higher_rows=closed_bars(h1),
                                          strategy_version="trendline-first-v5", target_model="h1-structure")
        self.assertEqual(V5.evaluate(market(closed + [closed[-1]], h1)), expected)


class SessionContextTests(unittest.TestCase):
    def test_session_context_uses_closed_bars_the_closed_price_and_the_bar_close_time(self):
        closed, _, atr = case(3)
        last = closed[-1]
        opened = corrected_bar_time(BASIS)(last)
        expected = compute_session_context(closed, float(last["close"]), opened + scanner_m15(), corrected_bar_time(BASIS))
        self.assertEqual(V5.closed_session_context(closed, BASIS), expected)
        # Through evaluate: an extreme forming bar (price far away) leaves the recorded session fields unchanged.
        h1 = h1_rows(closed + [closed[-1]])
        variants = forming_variants(last, atr)
        a, b = (V5.evaluate(market(closed + [variants[k]], h1)) for k in ("flat", "surge_up"))
        self.assertEqual(a["score_breakdown"]["session"], b["score_breakdown"]["session"])
        self.assertEqual(a, b)


def scanner_m15():
    from strategies.trendline import M15
    return M15


class StructuralTargetTests(unittest.TestCase):
    ROWS = [{"high": 101.0, "low": 99.5}]

    def levels(self, direction, m15_highs, m15_lows, h1_highs, h1_lows):
        return scanner._trade_levels(self.ROWS, direction, 100.0, 1.0, m15_highs, m15_lows, 100.3, "RESISTANCE",
                                     structural_levels=(h1_highs, h1_lows))

    def test_target_is_the_nearest_h1_swing_not_a_minor_m15_swing(self):
        long = self.levels("LONG", [(0, 100.4), (1, 100.7)], [(0, 99.5)], [(0, 103.2), (1, 105.0)], [])
        self.assertEqual(long["take_profit"], 103.2)
        self.assertEqual(long["target_basis"], "H1_SWING")
        self.assertEqual(long["stop_loss"], scanner._trade_levels(self.ROWS, "LONG", 100.0, 1.0, [(0, 100.4)], [(0, 99.5)], 100.3, "RESISTANCE")["stop_loss"],
                         "the stop is unchanged")
        short = self.levels("SHORT", [(0, 100.5)], [(0, 99.8)], [], [(0, 97.1), (1, 95.0)])
        self.assertEqual(short["take_profit"], 97.1)

    def test_an_h1_barrier_just_ahead_is_never_jumped(self):
        levels = self.levels("LONG", [], [(0, 99.5)], [(0, 100.1), (1, 104.0)], [])
        self.assertEqual(levels["take_profit"], 100.1)
        self.assertLess(levels["rr"], 1.5)

    def test_no_structural_target_means_no_target_and_no_projection(self):
        levels = self.levels("LONG", [(0, 100.5)], [(0, 99.5)], [(0, 98.0)], [])
        self.assertIsNone(levels["take_profit"])
        self.assertIsNone(levels["rr"])
        self.assertIsNone(levels["target_basis"])
        self.assertIsNotNone(levels["stop_loss"])

    def test_targets_are_in_the_trade_direction_and_ahead_of_entry(self):
        for seed in SEEDS:
            result = v5_scan(seed)
            if result["take_profit"] is None or result["direction"] is None:
                continue
            with self.subTest(seed=seed):
                if result["direction"] == "LONG":
                    self.assertGreater(result["take_profit"], result["entry"])
                else:
                    self.assertLess(result["take_profit"], result["entry"])
                h1_highs, h1_lows = scanner._swings(closed_bars(case(seed)[1]))
                pivots = [p for _, p in (h1_highs if result["direction"] == "LONG" else h1_lows)]
                self.assertIn(result["take_profit"], [round(p, 8) for p in pivots], "target is an H1 swing price")

    def test_the_target_never_uses_future_bars(self):
        # The newest closed H1 bar is the highest high, but a swing needs two later bars:
        # it is not a pivot yet, so it cannot be a target.
        h1 = [{"high": 100 + i * 0.1, "low": 99 + i * 0.1} for i in range(20)] + [{"high": 110.0, "low": 101.0}]
        highs, _ = scanner._swings(h1)
        self.assertNotIn(110.0, [p for _, p in highs])
        levels = scanner._trade_levels(self.ROWS, "LONG", 100.0, 1.0, [], [(0, 99.5)], 0.0, "NONE", structural_levels=scanner._swings(h1))
        self.assertIsNone(levels["take_profit"])


class RiskRewardGateTests(unittest.TestCase):
    def test_the_gate_is_unchanged_below_rejects_above_can_pass(self):
        seen = {"rejected_below": 0, "passed_above": 0, "no_target": 0}
        for seed in range(150):
            result = v5_scan(seed)
            rr = result["rr"]
            expected = result["state"] == "CONFIRMING" and result["trendline_gate"] and result["confirmation_alignment"] and (rr or 0) >= 1.5
            with self.subTest(seed=seed):
                self.assertEqual(result["strategy_valid"], expected)
            if result["state"] == "CONFIRMING":
                seen["rejected_below" if (rr is not None and rr < 1.5) else "passed_above" if result["strategy_valid"] else "no_target"] += 1
        self.assertGreater(seen["rejected_below"], 0)
        self.assertGreater(seen["passed_above"], 0, "a legitimate >= 1.5R structural target can confirm")
        self.assertGreater(seen["no_target"], 0)

    def test_a_setup_below_one_and_a_half_r_is_rejected_with_its_reason(self):
        result = v5_scan(5)
        self.assertEqual(result["state"], "CONFIRMING")
        self.assertLess(result["rr"], 1.5)
        self.assertFalse(result["strategy_valid"])
        self.assertIn("below the preferred 1.5R", result["reason"])

    def test_a_legitimate_structural_target_above_one_and_a_half_r_confirms(self):
        closed, h1, _ = case(31)
        result = V5.evaluate(market(closed + [closed[-1]], h1))
        self.assertTrue(result["strategy_valid"])
        self.assertGreaterEqual(result["rr"], 1.5)
        self.assertEqual(result["target_basis"], "H1_SWING")


class V4UnchangedTests(unittest.TestCase):
    def test_v5_is_the_registered_live_trendline_and_v4_is_retired(self):
        registry = build_default_registry()
        self.assertEqual((TRENDLINE, registry.get(TRENDLINE).version, registry.mode(TRENDLINE)), ("trendline_v5", "trendline-first-v5", "LIVE"))
        self.assertIsInstance(registry.get(TRENDLINE), TrendlineV5Strategy)
        # One trendline only: the retired v4 ("trendline") and the ended shadow experiment are not registered.
        self.assertEqual([i for i in registry.registered() if "trendline" in i], ["trendline_v5"])

    def test_v4_output_is_the_default_scanner_on_all_rows(self):
        for seed in SEEDS:
            full = m15_rows(seed)
            h1 = h1_rows(full)
            result = V4.evaluate(market(full, h1))
            with self.subTest(seed=seed):
                self.assertEqual(result, scanner.analyze_symbol("XAUUSD", full, spread=0.02, higher_rows=h1, strategy_version="trendline-first-v4"))
                self.assertNotIn("target_basis", result)


if __name__ == "__main__":
    unittest.main()
