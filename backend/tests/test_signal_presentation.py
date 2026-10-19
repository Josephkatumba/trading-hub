"""T-031B: setup names and trade rationales come only from recorded strategy evidence."""
from __future__ import annotations

import unittest

import signal_presentation as sp


def trendline(family, label, structure="Lower highs + lower lows", price_action="Bearish price action",
              momentum="BULLISH", version="trendline-first-v5.1"):
    return {"setup_type": family, "strategy_version": version, "timeframe": "M15",
            "features": {"trendline": label, "structure": structure, "price_action": price_action, "momentum": momentum}}


SR = {"setup_type": "SR_BOUNCE", "timeframe": "M15", "strategy_evidence": {
    "family": "SR_BOUNCE", "rejection": {"confirmed": True},
    "level": {"type": "RESISTANCE", "price": 25463.958823529414, "reactions": 8, "higher_timeframe_confluence": True}}}
TM = {"setup_type": "TM_PULLBACK_CONTINUATION", "timeframe": "M15", "strategy_evidence": {
    "trend": {"h4": {"direction": "SHORT"}, "d1": {"status": "AGREES"}},
    "momentum": {"impulse_atr": 5.7302}, "pullback": {"retracement": 0.4304, "controlled": True},
    "confirmation": {"rules": {"h1_aligned": True, "resumption": True}}}}
SMC = {"setup_type": "SMC_CHOCH_SWEEP_REVERSAL", "timeframe": "M15", "strategy_evidence": {
    "family": "SMC_CHOCH_SWEEP_REVERSAL", "htf": {"trend": "BULLISH"},
    "structure": {"last_break": {"kind": "CHOCH", "direction": "BULLISH"}},
    "liquidity_sweep": {"swept_level": 7713.2}, "poi": {"type": "ORDER_BLOCK"},
    "candle_confirmation": {"pattern": "engulfing"},
    "confirmation": {"rules": {"htf_aligned": True, "structure_shift": True, "liquidity": True, "poi_retest": True}}}}


class SetupNameTests(unittest.TestCase):
    def test_trendline_names_follow_the_recorded_family(self):
        self.assertEqual(sp.setup_name("trendline_v5", trendline("BREAK", "Trendline support break retest rejected"), "SHORT"),
                         "Break & Retest")
        self.assertEqual(sp.setup_name("trendline_v5", trendline("BREAK", "Trendline support break", version="trendline-first-v5"),
                                       "SHORT"), "Break")
        self.assertEqual(sp.setup_name("trendline_v5", trendline("REVERSAL", "Trendline resistance rejection"), "SHORT"),
                         "Bounce")

    def test_no_trend_reversal_label_is_invented(self):
        for family in ("BREAK", "REVERSAL", None, "WATCHING"):
            name = sp.setup_name("trendline_v5", trendline(family, "Trendline support rejection"), "LONG")
            self.assertNotIn("Reversal", name)

    def test_other_strategies(self):
        self.assertEqual(sp.setup_name("support_resistance", SR, "SHORT"), "Resistance Rejection")
        retest = {**SR, "setup_type": "SR_BREAK_RETEST", "strategy_evidence": {**SR["strategy_evidence"], "family": "SR_BREAK_RETEST",
                  "level": {**SR["strategy_evidence"]["level"], "type": "SUPPORT"}}}
        self.assertEqual(sp.setup_name("support_resistance", retest, "LONG"), "Support Break & Retest")
        self.assertEqual(sp.setup_name("trend_momentum", TM, "SHORT"), "Pullback Continuation")
        self.assertEqual(sp.setup_name("smc", SMC, "LONG"), "Liquidity Sweep & CHoCH")
        self.assertEqual(sp.setup_name("smc", {"setup_type": "SMC_BOS_CONTINUATION"}, "LONG"), "BOS Continuation")
        self.assertEqual(sp.strategy_name("trend_momentum"), "Trend & Momentum")


class RationaleTests(unittest.TestCase):
    def check(self, strategy_id, snapshot, direction, entry, expected):
        result = sp.rationale(strategy_id, snapshot, direction, "M15", entry)
        self.assertEqual(result["text"], expected)
        self.assertEqual(result["basis"], "evidence")
        self.assertLessEqual(len(result["text"].split()), sp.MAX_WORDS)

    def test_trendline_bounce_mentions_only_agreeing_evidence(self):
        # Momentum was BULLISH on this SHORT: it is not claimed as support.
        self.check("trendline_v5", trendline("REVERSAL", "Trendline resistance rejection"), "SHORT", 0.69731,
                   "Price tested the falling resistance trendline and closed back below it on M15, "
                   "with a lower-high, lower-low structure and bearish price action.")

    def test_trendline_break_and_retest(self):
        snap = trendline("BREAK", "Trendline support break retest rejected", structure="Mixed structure",
                         price_action="Bullish price action", momentum="BEARISH")
        self.check("trendline_v5", snap, "SHORT", 100.0,
                   "Price broke the rising support trendline, retested it and closed below it with a rejection candle "
                   "on M15, with bearish momentum.")

    def test_support_resistance_level_and_rejection(self):
        self.check("support_resistance", SR, "SHORT", 25466.7,
                   "Price rejected resistance at 25464.0 (8 prior reactions, H4/D1 confluence) with a confirmed M15 rejection candle.")

    def test_trend_momentum_trend_and_momentum_evidence(self):
        self.check("trend_momentum", TM, "SHORT", 4265.0,
                   "H4 downtrend with H1 aligned; after a 5.7 ATR impulse and a 43% pullback, price resumed lower on M15, with D1 agreeing.")

    def test_smc_structure_sweep_and_order_block(self):
        self.check("smc", SMC, "LONG", 7713.9,
                   "Liquidity sweep of 7713.2 then an M15 bullish CHoCH; price retested the order block and confirmed "
                   "with an engulfing candle, in line with the bullish H4 trend.")

    def test_smc_without_sweep_does_not_claim_one(self):
        snap = {**SMC, "strategy_evidence": {**SMC["strategy_evidence"], "confirmation": {"rules": {
            "structure_shift": True, "liquidity": False, "poi_retest": False, "htf_aligned": False}}}}
        text = sp.rationale("smc", snap, "LONG", "M15", 7713.9)["text"]
        self.assertEqual(text, "M15 bullish CHoCH.")
        self.assertNotIn("sweep", text.lower())

    def test_missing_evidence_falls_back_to_a_plain_fact(self):
        for strategy_id, snap in (("support_resistance", {"strategy_evidence": {"level": {}}}),
                                  ("trend_momentum", {}), ("smc", None), ("trendline_v5", {"features": {}})):
            result = sp.rationale(strategy_id, snap, "LONG", "M15", 1.0)
            self.assertEqual(result["basis"], "fallback")
            self.assertTrue(result["text"].startswith("All ") and result["text"].endswith("confirmation rules passed on the M15 chart."))

    def test_unconfirmed_rejection_is_not_claimed(self):
        snap = {**SR, "strategy_evidence": {**SR["strategy_evidence"], "rejection": {"confirmed": False}}}
        self.assertEqual(sp.rationale("support_resistance", snap, "SHORT", "M15", 25466.7)["basis"], "fallback")

    def test_version_is_recorded(self):
        self.assertEqual(sp.rationale("smc", SMC, "LONG", "M15", 7713.9)["version"], sp.RATIONALE_VERSION)


if __name__ == "__main__":
    unittest.main()
