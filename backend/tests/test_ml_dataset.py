import unittest
from datetime import datetime, timezone

from ml_dataset import (audit_candle_ordering, audit_outcome_chronology,
                        prepare_dataset, snapshot_features)
from outcomes import derive_market_outcome


def snapshot(**overrides):
    row = {
        "record_type": "setup_snapshot", "setup_id": "s1", "observation_id": "o1",
        "observed_at": "2026-01-01T00:00:00+00:00",
        "source_timestamp": "2025-12-31T23:59:00+00:00", "symbol": "XAUUSD",
        "timeframe": "M15", "direction": "LONG", "reference_price": 100.0,
        "proposed_entry": 100.1, "proposed_stop_loss": 98.0,
        "proposed_take_profit": 104.0, "lifecycle_state": "ACTIVE", "score": 70,
        "features": {"rsi": 55.0, "momentum": "BULLISH", "higher_timeframe_bias": "BULLISH"},
        "rule_evidence": {"strategy_valid": True}, "score_breakdown": {},
        "session": {"session": "London"},
        "time_provenance": {"timezone_normalization_status": "VERIFIED", "source_time_basis": "UTC"},
        "data_quality": {"status": "OK", "flags": [], "timestamp_quality": "VERIFIED"},
    }
    row.update(overrides)
    return row


class MLDatasetTests(unittest.TestCase):
    def test_candle_timestamp_ordering_detects_inversion_and_duplicates(self):
        good = audit_candle_ordering([{"time": 1}, {"time": 2}, {"time": 2}])
        bad = audit_candle_ordering([{"time": 2}, {"time": 1}])
        self.assertTrue(good["chronological"])
        self.assertEqual(good["duplicate_adjacent_timestamps"], 1)
        self.assertFalse(bad["chronological"])
        self.assertEqual(bad["out_of_order_pairs"], 1)

    def test_feature_schema_is_allowlisted_and_excludes_future_data(self):
        row = snapshot(source_timestamp="2099-01-01T00:00:00+00:00",
                       outcome={"label": "WIN"}, analyst_output={"classification": "CONFIRMED"},
                       future_price=999, resolved_at="2099-01-02T00:00:00+00:00")
        features = snapshot_features(row)
        self.assertIn("features.rsi", features)
        self.assertNotIn("rule_evidence.strategy_valid", features)
        self.assertNotIn("source_timestamp", features)
        self.assertNotIn("outcome", features)
        self.assertNotIn("future_price", features)
        self.assertNotIn("analyst_output", features)
        self.assertNotIn("resolved_at", features)

    def test_future_source_time_is_degraded_even_if_stored_quality_says_ok(self):
        row = snapshot(source_timestamp="2026-01-01T00:15:00+00:00")
        report = prepare_dataset([row], [], [], [], horizons=("15m",))
        self.assertEqual(report["timestamp_audit"]["counts"]["future_source_timestamp"], 1)
        self.assertEqual(report["statistics"]["degraded_timestamp_observations"], 1)
        self.assertEqual(report["statistics"]["usable_observations"], 0)

    def test_valid_timezone_aware_source_time_is_not_degraded(self):
        row = snapshot(source_timestamp="2025-12-31T20:59:00-03:00")
        report = prepare_dataset([row], [], [], [], horizons=("15m",))
        self.assertEqual(report["timestamp_audit"]["counts"]["source_timestamp_before_observation"], 1)
        self.assertEqual(report["statistics"]["degraded_timestamp_observations"], 0)

    def test_confirmed_watch_and_terminal_lifecycle_cohorts_are_separate(self):
        first = snapshot(setup_id="s1")
        watch = snapshot(setup_id="s2", observation_id="o2", direction="SHORT",
                         rule_evidence={"strategy_valid": False})
        report = prepare_dataset([first, watch], [], [
            {"setup_id": "s1", "to_state": "INVALIDATED"},
            {"setup_id": "s2", "to_state": "EXPIRED"}], [], horizons=("15m",))
        self.assertEqual(report["statistics"]["confirmed_observations"], 1)
        self.assertEqual(report["statistics"]["watch_observations"], 1)
        self.assertEqual(report["statistics"]["invalidated_observations"], 1)
        self.assertEqual(report["statistics"]["expired_observations"], 1)
        self.assertIn("INVALIDATED", report["dataset_rows"][0]["cohort_tags"])
        self.assertIn("WATCH", report["dataset_rows"][1]["cohort_tags"])

    def test_reused_legacy_observation_id_is_not_used_for_label_join(self):
        first = {"observation_id": "legacy-shared", "observed_at": "2026-01-01T00:00:00+00:00",
                 "timestamp": "2026-01-01T00:00:00+00:00", "symbol": "XAUUSD", "direction": "LONG",
                 "price": 100, "state": "CONFIRMING", "strategy_valid": True}
        second = {**first, "observed_at": "2026-01-01T00:15:00+00:00",
                  "timestamp": "2026-01-01T00:15:00+00:00"}
        existing = {"record_type": "market_outcome", "outcome_id": "m1", "setup_id": "legacy",
                    "observation_id": "legacy-shared", "horizon": "4h", "label": "WIN"}
        report = prepare_dataset([first, second], [existing], [],
                                 [{"observation_id": "legacy-shared"}], horizons=("4h",))
        self.assertEqual(report["statistics"]["ambiguous_observation_id_rows"], 2)
        self.assertEqual(report["statistics"]["usable_observations"], 0)
        self.assertTrue(all("AMBIGUOUS_OBSERVATION_ID" in row["cohort_tags"]
                            for row in report["dataset_rows"]))
        self.assertEqual(report["outcome_chronology"]["counts"]["ambiguous_observation_id"], 1)

    def test_outcome_label_is_joined_from_existing_outcome_not_fabricated(self):
        row = snapshot()
        report = prepare_dataset([row], [], [], [{"observation_id": "o1"}], horizons=("15m",))
        self.assertEqual(report["dataset_rows"][0]["target"]["label"], "PENDING")
        self.assertEqual(report["dataset_rows"][0]["target"]["readiness"], "NOT_READY_OUTCOME")
        self.assertEqual(report["statistics"]["wins"], 0)
        self.assertEqual(report["statistics"]["losses"], 0)
        existing = {"record_type": "market_outcome", "outcome_id": "m1", "setup_id": "s1",
                    "observation_id": "o1", "horizon": "15m", "label": "WIN",
                    "resolved_at": "2026-01-01T00:16:00+00:00",
                    "label_definition": "target-invalidation-first-v1", "timestamp_quality": "VERIFIED",
                    "data_quality": {"timestamp_quality": "VERIFIED"},
                    "outcome_time_validity": "OUTCOME_TIME_VALID",
                    "outcome_time_validation": {"outcome_time_validity": "OUTCOME_TIME_VALID",
                        "first_candidate_candle_timestamp": "2026-01-01T00:15:00+00:00",
                        "last_candidate_candle_timestamp": "2026-01-01T00:15:00+00:00",
                        "every_candidate_strictly_after_observation": True,
                        "candidate_candles_chronological": True}}
        report = prepare_dataset([row], [existing], [], [{"observation_id": "o1"}], horizons=("15m",))
        self.assertEqual(report["dataset_rows"][0]["target"]["label"], "WIN")
        self.assertEqual(report["statistics"]["usable_observations"], 1)
        self.assertEqual(report["statistics"]["ML_READY_OBSERVATIONS"], 1)
        for label in ("NO_HIT", "AMBIGUOUS"):
            non_binary = {**existing, "outcome_id": "mkt_" + label, "label": label}
            report = prepare_dataset([row], [non_binary], [], [{"observation_id": "o1"}], horizons=("15m",))
            self.assertFalse(report["dataset_rows"][0]["ml_usable"])

    def test_historical_outcomes_are_quarantined_and_not_training_rows(self):
        row = snapshot()
        historical = {"record_type": "market_outcome", "outcome_id": "old", "setup_id": "s1",
            "observation_id": "o1", "horizon": "15m", "label": "WIN"}
        report = prepare_dataset([row], [historical], [], [{"observation_id": "o1"}], horizons=("15m",))
        projected = report["dataset_rows"][0]
        self.assertEqual(projected["target"]["readiness"], "QUARANTINED_HISTORICAL_OUTCOME")
        self.assertFalse(projected["ml_usable"])
        self.assertEqual(report["statistics"]["wins"], 0)
        self.assertEqual(report["statistics"]["quarantined_historical_outcomes"], 1)
        self.assertIn("OUTCOME_TIMESTAMP_QUALITY_MISSING_OR_UNVERIFIED",
                      report["outcome_quarantine"]["reason_counts"])
        self.assertEqual(report["outcome_quarantine"]["examples"][0]["resolved_at"], None)

    def test_unverified_snapshot_time_is_not_ready(self):
        row = snapshot(time_provenance={"timezone_normalization_status": "UNVERIFIED"})
        report = prepare_dataset([row], [], [], [], horizons=("15m",))
        self.assertEqual(report["dataset_rows"][0]["target"]["readiness"], "NOT_READY_TIMESTAMP")

    def test_prospective_time_counts_require_raw_provenance_and_backend_times(self):
        verified = snapshot(time_provenance={"timezone_normalization_status": "VERIFIED",
            "backend_received_at": "2026-01-01T00:00:00Z",
            "observation_time": "2026-01-01T00:00:01Z",
            "bar_open_time": {"raw_mt5_epoch": 1767225600},
            "tick_time": {"raw_mt5_epoch": 1767225601}})
        unverified = snapshot(observation_id="o2", time_provenance={
            "timezone_normalization_status": "UNVERIFIED",
            "backend_received_at": "2026-01-01T00:00:00Z",
            "observation_time": "2026-01-01T00:00:01Z",
            "bar_open_time": {"raw_mt5_epoch": 1767225600},
            "tick_time": {"raw_mt5_epoch": 1767225601}})
        report = prepare_dataset([verified, unverified], [], [], [], horizons=("15m",))
        stats = report["statistics"]
        self.assertEqual(stats["PROSPECTIVE_OBSERVATIONS"], 2)
        self.assertEqual(stats["TIME_VALID_OBSERVATIONS"], 1)
        self.assertEqual(stats["TIME_UNVERIFIED_OBSERVATIONS"], 1)

    def test_prospective_future_source_is_not_counted_time_valid(self):
        future = snapshot(source_timestamp="2026-01-01T03:00:00+00:00",
            time_provenance={"timezone_normalization_status": "VERIFIED",
                "backend_received_at": "2026-01-01T00:00:00Z",
                "observation_time": "2026-01-01T00:00:01Z",
                "bar_open_time": {"raw_mt5_epoch": 1767225600},
                "tick_time": {"raw_mt5_epoch": 1767225601}})
        report = prepare_dataset([future], [], [], [], horizons=("15m",))
        self.assertEqual(report["statistics"]["TIME_VALID_OBSERVATIONS"], 0)

    def test_timestamp_audit_includes_raw_interpreted_and_persisted_examples(self):
        row = snapshot(time_provenance={"timezone_normalization_status": "UNVERIFIED",
            "backend_received_at": "2026-01-01T00:00:01Z",
            "observation_time": "2026-01-01T00:00:02Z",
            "bar_open_time": {"raw_mt5_epoch": 1767225600,
                "interpreted_source_time": "2026-01-01T00:00:00",
                "normalization_status": "UNVERIFIED"},
            "tick_time": {"raw_mt5_epoch": 1767225601,
                "interpreted_source_time": "2026-01-01T00:00:01",
                "normalization_status": "UNVERIFIED"}})
        report = prepare_dataset([row], [], [], [], horizons=("15m",))
        example = report["timestamp_audit"]["examples"][0]
        self.assertEqual(example["raw_mt5_bar_epoch"], 1767225600)
        self.assertEqual(example["interpreted_mt5_bar_time"], "2026-01-01T00:00:00")
        self.assertEqual(example["persisted_observed_at"], row["observed_at"])

    def test_structured_snapshot_missing_required_decision_fields_is_not_ready(self):
        row = snapshot(reference_price=None, direction=None)
        report = prepare_dataset([row], [], [], [], horizons=("15m",))
        self.assertEqual(report["dataset_rows"][0]["target"]["readiness"], "NOT_READY_MISSING_FEATURES")

    def test_outcome_resolution_must_follow_observation_and_ohlc_path_is_sorted(self):
        row = snapshot()
        outcome = {"outcome_id": "m1", "observation_id": "o1",
                   "resolved_at": "2026-01-01T00:20:00+00:00"}
        self.assertEqual(audit_outcome_chronology([outcome], [row])["counts"]["resolution_not_before_observation"], 1)
        outcome["resolved_at"] = "2025-12-31T23:00:00+00:00"
        self.assertEqual(audit_outcome_chronology([outcome], [row])["counts"]["resolved_before_observation"], 1)

        bars = [
            {"time": datetime(2026, 1, 1, 0, 45, tzinfo=timezone.utc).timestamp(),
             "high": 101, "low": 99, "close": 100},
            {"time": datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc).timestamp(),
             "high": 105, "low": 99, "close": 104},
            {"time": datetime(2026, 1, 1, 0, 15, tzinfo=timezone.utc).timestamp(),
             "high": 101, "low": 99, "close": 100},
            {"time": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp(),
             "high": 101, "low": 99, "close": 100},
        ]
        result = derive_market_outcome(row, "1h", bars, "M15", target_price=104,
                                       invalidation_price=98,
                                       now=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc))
        self.assertEqual(result["label"], "WIN")
        self.assertEqual(result["future_price"], 100)


if __name__ == "__main__":
    unittest.main()
