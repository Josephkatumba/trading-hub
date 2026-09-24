from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from outcomes import derive_market_outcome, resolve_due_market_outcomes, validate_outcome_time


class MarketOutcomeLabelTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)
        self.snapshot = {"setup_id": "stp_a", "observation_id": "obs_a",
                         "observed_at": self.start.isoformat(), "reference_price": 100.0,
                         "source_timestamp": (self.start - timedelta(minutes=15)).isoformat(),
                         "direction": "LONG", "time_provenance": {
                             "timezone_normalization_status": "VERIFIED", "source_time_basis": "UTC"}}
        self.time = self.start

    def bars(self, first_high=104, first_low=96):
        values = []
        for index in range(4):
            values.append({"time": (self.start + timedelta(minutes=15*(index + 1))).timestamp(),
                           "high": first_high if index == 0 else 104,
                           "low": first_low if index == 0 else 96,
                           "close": 101})
        return values

    def outcome(self, bars):
        return derive_market_outcome(self.snapshot, "1h", bars, "M15",
            target_price=105, invalidation_price=95,
            now=self.start + timedelta(hours=1))

    def test_target_first_is_market_win(self):
        row = self.bars(first_high=106)
        outcome = self.outcome(row)
        self.assertEqual(outcome["label"], "WIN")
        self.assertEqual(outcome["outcome_time_validity"], "OUTCOME_TIME_VALID")
        self.assertEqual(outcome["outcome_status"], "OUTCOME_EVALUATED")
        validation = outcome["outcome_time_validation"]
        self.assertEqual(validation["candidate_candle_count"], 3)
        self.assertTrue(validation["every_candidate_strictly_after_observation"])
        self.assertEqual(validation["timestamp_quality"], "VERIFIED")

    def test_invalidation_first_is_market_loss(self):
        row = self.bars(first_low=94)
        self.assertEqual(self.outcome(row)["label"], "LOSS")

    def test_neither_barrier_is_no_hit_not_loss(self):
        self.assertEqual(self.outcome(self.bars())["label"], "NO_HIT")

    def test_same_candle_dual_touch_is_ambiguous(self):
        self.assertEqual(self.outcome(self.bars(first_high=106, first_low=94))["label"], "AMBIGUOUS")

    def test_incomplete_horizon_remains_pending(self):
        self.assertIsNone(derive_market_outcome(self.snapshot, "1h", self.bars(), "M15",
            target_price=105, invalidation_price=95, now=self.start + timedelta(minutes=45)))

    def test_pre_observation_bar_is_excluded_from_future_window(self):
        bars = [{"time": self.start.timestamp(), "high": 110, "low": 90, "close": 105}] + [
            {"time": (self.start + timedelta(minutes=15*i)).timestamp(),
             "high": 102, "low": 98, "close": 100} for i in range(1, 4)]
        result = self.outcome(bars)
        self.assertEqual(result["label"], "NO_HIT")
        self.assertEqual(result["future_price"], 100)

    def test_watch_without_decision_barriers_is_not_labeled(self):
        watch = {**self.snapshot, "rule_evidence": {"strategy_valid": False}}
        bars = [{"time": (self.start + timedelta(minutes=15*i)).timestamp(),
                 "high": 110, "low": 90, "close": 100} for i in range(1, 5)]
        rows = resolve_due_market_outcomes([], {"obs_a": watch}, {"XAUUSD": bars}, [],
            ("1h",), now=self.start + timedelta(hours=1), watch_snapshots=[watch])
        self.assertEqual(rows, [])

    def test_watch_with_valid_decision_barriers_gets_market_outcome(self):
        watch = {**self.snapshot, "record_type": "setup_snapshot", "symbol": "XAUUSD", "rule_evidence": {"strategy_valid": False},
                 "proposed_take_profit": 105, "invalidation_price": 95}
        bars = [{"time": (self.start + timedelta(minutes=15*i)).timestamp(),
                 "high": 106 if i == 1 else 102, "low": 98, "close": 101}
                for i in range(1, 5)]
        rows = resolve_due_market_outcomes([], {"obs_a": watch}, {"XAUUSD": bars}, [],
            ("1h",), now=self.start + timedelta(hours=1), watch_snapshots=[watch])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "WIN")

    def test_unverified_timestamp_snapshot_cannot_generate_outcome(self):
        unverified = {**self.snapshot, "time_provenance": {"timezone_normalization_status": "UNVERIFIED"}}
        self.assertIsNone(derive_market_outcome(unverified, "1h", self.bars(), "M15",
            target_price=105, invalidation_price=95, now=self.start + timedelta(hours=1)))

    def test_candidate_candle_before_observation_is_invalid(self):
        candidate = [{"time": (self.start - timedelta(minutes=15)).timestamp()}]
        result = validate_outcome_time(self.snapshot, candidate)
        self.assertEqual(result["outcome_time_validity"], "OUTCOME_TIME_INVALID")
        self.assertFalse(result["every_candidate_strictly_after_observation"])

    def test_candidate_candle_at_observation_is_invalid(self):
        result = validate_outcome_time(self.snapshot, [{"time": self.start.timestamp()}])
        self.assertEqual(result["outcome_time_validity"], "OUTCOME_TIME_INVALID")

    def test_candidate_candle_after_observation_is_valid(self):
        result = validate_outcome_time(self.snapshot, [
            {"time": (self.start + timedelta(minutes=15)).timestamp()}])
        self.assertEqual(result["outcome_time_validity"], "OUTCOME_TIME_VALID")
        self.assertTrue(result["every_candidate_strictly_after_observation"])
        self.assertEqual(result["candidate_candle_count"], 1)

    def test_unverified_basis_yields_unverified_chronology_and_no_label(self):
        unverified = {**self.snapshot, "time_provenance": {
            "timezone_normalization_status": "UNVERIFIED", "source_time_basis": "UNVERIFIED"}}
        future_bars = self.bars()
        result = validate_outcome_time(unverified, future_bars)
        self.assertEqual(result["outcome_time_validity"], "OUTCOME_TIME_UNVERIFIED")
        self.assertIsNone(derive_market_outcome(unverified, "1h", future_bars, "M15",
            target_price=105, invalidation_price=95, now=self.start + timedelta(hours=1)))

    def test_naive_snapshot_time_is_rejected_without_local_timezone_assumption(self):
        naive = {**self.snapshot, "observed_at": "2026-09-23T08:00:00"}
        self.assertIsNone(derive_market_outcome(naive, "1h", self.bars(), "M15",
            target_price=105, invalidation_price=95, now=self.start + timedelta(hours=1)))

    def test_naive_candidate_candle_time_is_invalid(self):
        result = validate_outcome_time(self.snapshot, [{"time": "2026-09-23T08:15:00"}])
        self.assertEqual(result["outcome_time_validity"], "OUTCOME_TIME_INVALID")

    def test_future_source_timestamp_is_invalid_even_when_timezone_is_configured(self):
        future = {**self.snapshot,
            "source_timestamp": (self.start + timedelta(hours=3)).isoformat()}
        result = validate_outcome_time(future, self.bars())
        self.assertEqual(result["outcome_time_validity"], "OUTCOME_TIME_INVALID")
        self.assertIsNone(derive_market_outcome(future, "1h", self.bars(), "M15",
            target_price=105, invalidation_price=95, now=self.start + timedelta(hours=1)))


if __name__ == "__main__":
    unittest.main()
