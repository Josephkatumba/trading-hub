"""SMC (smc-confluence-v1): detection, confluence requirements and TradeDen-only scope.

Synthetic, hand-built bars (tests/smc_fixtures.py); no MT5. Each test states the rule it
proves. A single FVG, order block or sweep is never a setup: every case below differs
from a valid one by exactly one required element.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g  # noqa: E402
import smc_fixtures as f  # noqa: E402

import strategies  # noqa: E402
from strategies import MarketInput  # noqa: E402
from strategies import smc  # noqa: E402
from strategies.price_action import confirm_rejection  # noqa: E402


def evaluate(frames: dict) -> dict:
    return smc.analyze_smc(MarketInput("XAUUSD", frames["M15"], bars=frames))


def smc_market(payload: dict, symbol: str = "XAUUSD") -> dict:
    """The market dict main builds for a non-trendline strategy result (verified provenance)."""
    last = payload.get("entry") or 100.0
    return {"symbol": symbol, "broker_symbol": symbol, "price": last, "bid": last, "ask": last, "spread": 0.0,
            "change_pct": 0.0, **payload, "timeframe": "M15", "higher_timeframes": ["H1", "H4"], "strategy_id": "smc",
            "strategy_version": payload["strategy_version"], "strategy_mode": "LIVE",
            "time_provenance": {"source_time_basis": "UTC", "timezone_normalization_status": "VERIFIED"},
            "source_timestamp": g.BASE_NOW.isoformat()}


class DetectionTests(unittest.TestCase):
    def test_structure_engine_reports_bos_and_choch_without_look_ahead(self):
        rows = f.bullish_choch()["M15"][:-1]
        ms = smc.market_structure(rows)
        self.assertEqual(ms["trend"], "BULLISH")
        self.assertEqual(ms["events"][-1]["kind"], "CHOCH")
        self.assertTrue(any(e["kind"] == "BOS" and e["direction"] == "BEARISH" for e in ms["events"]))
        # A break is decided at bar k from swings known by k: truncating the future changes nothing before k.
        k = ms["events"][-1]["index"]
        self.assertEqual(smc.market_structure(rows[:k + 1])["events"][-1], ms["events"][-1])

    def test_fvg_requires_a_real_gap_of_minimum_size(self):
        rows = f.bullish_bos()["M15"][:-1]
        gaps = smc.fair_value_gaps(rows, 0, len(rows), True, 0.1)
        self.assertTrue(gaps)
        for gap in gaps:
            self.assertGreater(float(rows[gap["index"] + 1]["low"]), float(rows[gap["index"] - 1]["high"]))
        self.assertEqual(smc.fair_value_gaps(rows, 0, len(rows), True, 1e9), [])


class SetupTests(unittest.TestCase):
    def test_bos_order_block_reaction_is_a_valid_setup(self):
        result = evaluate(f.bullish_bos("reaction"))
        self.assertEqual((result["state"], result["direction"], result["strategy_valid"], result["setup_family"]),
                         ("CONFIRMING", "LONG", True, "SMC_BOS_CONTINUATION"))
        evidence = result["strategy_evidence"]
        self.assertEqual(evidence["scope"], "TRADEDEN_SIGNAL_ONLY")
        self.assertEqual(set(evidence["confirmation"]["rules"]), set(smc.CONFIRMATION_RULES))
        self.assertTrue(all(evidence["confirmation"]["rules"].values()))
        self.assertEqual(evidence["candle_confirmation"]["pattern"], "wick_rejection")
        self.assertLess(result["stop_loss"], evidence["order_block"]["low"])
        self.assertGreaterEqual(result["rr"], smc.MIN_RR)
        json.dumps(result)                                                  # serialisable as persisted

    def test_choch_needs_a_liquidity_sweep(self):
        swept = evaluate(f.bullish_choch(sweep=True))
        self.assertEqual((swept["state"], swept["strategy_valid"], swept["setup_family"]),
                         ("CONFIRMING", True, "SMC_CHOCH_SWEEP_REVERSAL"))
        self.assertIsNotNone(swept["strategy_evidence"]["liquidity_sweep"])
        unswept = evaluate(f.bullish_choch(sweep=False))
        self.assertEqual((unswept["state"], unswept["strategy_valid"]), ("NO SETUP", False))
        self.assertIn("liquidity", unswept["strategy_evidence"]["confirmation"]["failed"])

    def test_states_follow_the_retest(self):
        self.assertEqual(evaluate(f.bullish_bos("no_retrace"))["state"], "WATCHING")
        developing = evaluate(f.bullish_bos("in_poi"))
        self.assertEqual((developing["state"], developing["strategy_valid"]), ("DEVELOPING", False))
        self.assertIn("reaction", developing["strategy_evidence"]["confirmation"]["failed"])
        self.assertEqual(evaluate(f.bullish_bos("invalidated"))["state"], "NO SETUP")

    def test_no_htf_alignment_no_setup(self):
        frames = f.bullish_bos("reaction")
        bear_h4 = f.bearish({"H4": frames["H4"]})["H4"]
        result = evaluate({**frames, "H4": bear_h4})
        self.assertEqual((result["state"], result["strategy_valid"]), ("NO SETUP", False))

    def test_short_mirror(self):
        result = evaluate(f.bearish(f.bullish_bos("reaction")))
        self.assertEqual((result["state"], result["direction"], result["strategy_valid"]), ("CONFIRMING", "SHORT", True))


class RegistrationTests(unittest.TestCase):
    def test_smc_is_live_in_tradeden_and_isolated(self):
        self.assertEqual(strategies.REGISTRY.mode("smc"), "LIVE")
        strategy = strategies.REGISTRY.get("smc")
        self.assertEqual((strategy.version, strategy.lifecycle), (smc.STRATEGY_VERSION, smc.CONFIRMED_EVENTS_LIFECYCLE))
        frames = f.bullish_bos("reaction")
        results = strategies.REGISTRY.evaluate(MarketInput("XAUUSD", frames["M15"], higher_rows=frames["H1"], bars=frames))
        self.assertTrue(results["smc"].ok)
        self.assertTrue(results["smc"].confirmed)


class PriceActionTests(unittest.TestCase):
    """The shared candle confirmation (strategies/price_action.py), LONG side."""

    def check(self, bars, touched=lambda i: True, outside=lambda i: True, earliest=0):
        rows = [{"time": i, "open": o, "high": h, "low": l, "close": c} for i, (o, h, l, c) in enumerate(bars)]
        return confirm_rejection(rows, True, touched, outside, earliest)

    def test_each_pattern_alone_confirms(self):
        wick = self.check([(10, 10.5, 9.5, 10), (10.6, 11, 9.8, 10.9)])              # wick 0.8 of 1.2
        self.assertEqual(wick["pattern"], "wick_rejection")
        engulf = self.check([(10.5, 10.6, 9.9, 10.0), (9.95, 10.8, 9.95, 10.7)], touched=lambda i: i == 0)
        self.assertEqual(engulf["pattern"], "engulfing")
        away = self.check([(10, 10.4, 9.8, 10.2), (10.2, 10.6, 10.2, 10.5)], touched=lambda i: i == 0)
        self.assertEqual(away["pattern"], "close_away")

    def test_a_plain_bullish_close_after_a_touch_does_not_confirm(self):
        result = self.check([(10, 10.6, 9.8, 10.2), (10.2, 10.5, 10.2, 10.4)], touched=lambda i: i == 0)
        self.assertFalse(result["confirmed"])
        self.assertFalse(self.check([(10, 10.5, 9.5, 10), (10.6, 11, 9.8, 10.9)], outside=lambda i: False)["confirmed"])
        self.assertFalse(self.check([(10, 10.4, 9.8, 10.2), (10.2, 10.6, 10.2, 10.5)], touched=lambda i: i == 0,
                                    earliest=1)["confirmed"])


if __name__ == "__main__":
    unittest.main()
