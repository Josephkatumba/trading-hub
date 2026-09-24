from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analyst import analyze_snapshot


class AnalystTests(unittest.TestCase):
    def test_confirmed_classification_uses_only_strategy_valid(self):
        snapshot = {"setup_id": "stp_a", "observation_id": "obs_a", "direction": "LONG",
                    "setup_type": "REVERSAL", "score": 20,
                    "rule_evidence": {"strategy_valid": True, "trendline_gate": True,
                                      "confirmation_alignment": True},
                    "features": {"higher_timeframe_bias": "BEARISH", "price_action_state": "BULLISH",
                                 "momentum": "BULLISH", "rr": 2.0, "atr": 1.2},
                    "score_breakdown": {}, "data_quality": {"status": "OK"}}
        result = analyze_snapshot(snapshot, "2026-09-23T12:00:00Z")
        self.assertEqual(result["classification"], "CONFIRMED")
        self.assertTrue(result["conflicts"])
        self.assertEqual(result["risk_context"]["atr"], 1.2)

    def test_watch_missing_fields_and_traceability(self):
        snapshot = {"setup_id": "stp_b", "observation_id": "obs_b", "direction": "SHORT",
                    "setup_type": "BREAK", "score": 50,
                    "rule_evidence": {"strategy_valid": False, "trendline_gate": False,
                                      "confirmation_alignment": False},
                    "features": {"momentum": "BULLISH"}, "score_breakdown": {}}
        result = analyze_snapshot(snapshot)
        self.assertEqual(result["classification"], "WATCH")
        refs = {item["source_field"] for item in result["evidence"]}
        self.assertIn("features.momentum", refs)
        for item in result["confirmations"] + result["conflicts"] + result["missing_confirmations"]:
            self.assertTrue(item["source_field"])
            if item["source_value"] is not None:
                self.assertIsNotNone(item["source_value"])
        self.assertIsNone(result["risk_context"]["take_profit"])

    def test_confirmed_invalidation_has_traceable_evidence(self):
        snapshot = {"setup_id": "s", "observation_id": "o", "direction": "SHORT",
            "reference_price": 100, "proposed_entry": 99.9, "invalidation_price": 102,
            "proposed_stop_loss": 102, "proposed_take_profit": 96, "score": 75,
            "rule_evidence": {"strategy_valid": True, "trendline_gate": True,
                "confirmation_alignment": True, "invalidation_hint": 102,
                "reason": "Resistance rejection; bearish close"},
            "features": {"trendline": "Trendline resistance rejection", "trendline_state": "REVERSAL",
                "price_action_state": "BEARISH", "nearest_level": 99.9,
                "nearest_level_type": "RESISTANCE", "nearest_level_atr": 0,
                "higher_timeframe_bias": "BEARISH", "momentum": "BEARISH",
                "rr": 2.0, "atr": 1.0},
            "session": {"session": "London", "session_alignment": "aligned"},
            "score_breakdown": {"trendline": 20},
            "data_quality": {"status": "OK", "received_bars": 300, "expected_bars": 300}}
        result = analyze_snapshot(snapshot, "2026-09-23T12:00:00Z")
        self.assertEqual(result["classification"], "CONFIRMED")
        self.assertEqual(result["risk_context"], {"reference_price": 100, "entry": 99.9,
            "invalidation": 102, "stop_loss": 102, "take_profit": 96, "rr": 2.0, "atr": 1.0})
        for item in result["confirmations"]:
            self.assertIn("source_field", item)
            self.assertIsNotNone(item["source_value"])

    def test_confirmed_missing_invalidation_is_safe_and_reports_missing_indicators(self):
        result = analyze_snapshot({"setup_id": "s", "observation_id": "o", "direction": "LONG",
            "rule_evidence": {"strategy_valid": True}, "features": {"higher_timeframe_bias": "BULLISH"}})
        self.assertEqual(result["classification"], "CONFIRMED")
        self.assertIsNone(result["risk_context"]["invalidation"])
        missing_claims = {item["claim"] for item in result["missing_confirmations"]}
        for label in ("H4 bias", "MACD", "ADX", "Volume", "Session alignment"):
            self.assertTrue(any(label in claim and "unavailable" in claim for claim in missing_claims))

    def test_higher_timeframe_alignment_and_conflict_directions(self):
        for direction, bias, is_conflict in (
            ("SHORT", "BULLISH", True), ("SHORT", "BEARISH", False),
            ("LONG", "BULLISH", False), ("LONG", "BEARISH", True),
            ("LONG", "NEUTRAL", False)):
            result = analyze_snapshot({"setup_id": "s", "observation_id": "o", "direction": direction,
                "rule_evidence": {"strategy_valid": True},
                "features": {"higher_timeframe_bias": bias}})
            htf = [item for item in result["conflicts"] if item["source_field"] == "features.higher_timeframe_bias"]
            self.assertEqual(bool(htf), is_conflict, (direction, bias))
            if not is_conflict and bias != "NEUTRAL":
                self.assertTrue(any(item["source_field"] == "features.higher_timeframe_bias"
                                    for item in result["confirmations"]))

    def test_risk_fields_can_be_incomplete_without_failure(self):
        result = analyze_snapshot({"setup_id": "s", "observation_id": "o", "direction": "SHORT",
            "invalidation_price": 12, "rule_evidence": {"strategy_valid": True}, "features": {}})
        self.assertEqual(result["risk_context"]["invalidation"], 12)
        self.assertIsNone(result["risk_context"]["entry"])
        self.assertIsNone(result["risk_context"]["take_profit"])


if __name__ == "__main__":
    unittest.main()
