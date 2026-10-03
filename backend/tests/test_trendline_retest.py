"""trendline-first-v5.1: a BREAK confirms only after a retest of the broken line rejects it.

Seeded random-walk bars (tests/v5_fixtures.py), evaluated bar by bar exactly as the live
v5 strategy sees them (closed bars, H1 structural targets). v5 (break_confirmation
"break-bar") is the baseline; v5.1 is "retest-rejection".
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v5_fixtures as vf  # noqa: E402

import scanner  # noqa: E402
import strategies  # noqa: E402

SEEDS = (0, 1, 2)


def windows(seed: int, count: int = 700):
    m15 = vf.m15_rows(seed, count)
    h1 = vf.h1_rows(m15)
    for end in range(250, count):
        rows = m15[:end]
        yield end, rows, [r for r in h1 if r["time"] <= rows[-1]["time"]]


def both(rows, higher):
    kwargs = {"higher_rows": higher, "target_model": "h1-structure"}
    return (scanner.analyze_symbol("X", rows, **kwargs),
            scanner.analyze_symbol("X", rows, break_confirmation="retest-rejection", **kwargs))


class RetestRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pairs = [(seed, end, rows, *both(rows, higher)) for seed in SEEDS for end, rows, higher in windows(seed)]

    def test_break_confirms_only_on_a_rejected_retest_after_the_break_bar(self):
        confirmed = [(seed, end, new) for seed, end, _, _, new in self.pairs
                     if new["state"] == "CONFIRMING" and new["setup_family"] == "BREAK"]
        self.assertTrue(confirmed, "the fixtures contain break-and-retest confirmations")
        for seed, end, new in confirmed:
            retest = new["trendline_retest"]
            self.assertTrue(retest["confirmed"] and not retest["failed"], (seed, end))
            self.assertGreaterEqual(retest["bars_since_break"], 1, "the break candle is never its own retest")
            self.assertIn(retest["pattern"], ("wick_rejection", "engulfing", "close_away"))

    def test_fewer_break_confirmations_and_reversals_unchanged(self):
        old_breaks = sum(1 for *_, old, _ in self.pairs if old["strategy_valid"] and old["setup_family"] == "BREAK")
        new_breaks = sum(1 for *_, new in self.pairs if new["strategy_valid"] and new["setup_family"] == "BREAK")
        self.assertLess(new_breaks, old_breaks)
        for seed, end, _, old, new in self.pairs:
            if old["setup_family"] == "REVERSAL":
                self.assertEqual({k: v for k, v in new.items() if k != "trendline_retest"}, old, (seed, end))

    def test_the_break_bar_itself_never_confirms(self):
        for seed, end, rows, _, new in self.pairs:
            retest = new.get("trendline_retest")
            if retest and retest["bars_since_break"] == 0:
                self.assertNotEqual(new["state"], "CONFIRMING", (seed, end))

    def test_live_strategy_is_v51_and_v5_output_is_unchanged(self):
        live = strategies.REGISTRY.get(strategies.TRENDLINE)
        self.assertEqual((live.strategy_id, live.version), ("trendline_v5", "trendline-first-v5.1"))
        _, rows, higher = next(windows(0))
        v5 = scanner.analyze_symbol("X", rows, higher_rows=higher, target_model="h1-structure")
        self.assertNotIn("trendline_retest", v5)


if __name__ == "__main__":
    unittest.main()
