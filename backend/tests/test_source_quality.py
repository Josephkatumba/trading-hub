from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analyst import analyze_snapshot
from market_time import (combined_normalization_status, normalize_mt5_epoch,
    mt5_epoch_to_utc_iso, parse_aware_utc)
from observations import _quality, _snapshot


class SourceQualityTests(unittest.TestCase):
    def test_unverified_future_clock_is_preserved_and_degraded_not_clamped(self):
        observed = datetime(2026, 9, 23, 9, 24, tzinfo=timezone.utc)
        source = observed + timedelta(hours=3)
        result = normalize_mt5_epoch(source.timestamp(), None)
        quality = _quality({"source_timestamp": None, "time_provenance": {
            "normalization_status": result["normalization_status"]},
            "tick_age_seconds": None, "candle_age_seconds": 230,
            "backend_received_at": observed.isoformat()}, observed.isoformat())
        self.assertEqual(result["raw_mt5_epoch"], source.timestamp())
        self.assertEqual(result["normalization_status"], "UNVERIFIED")
        self.assertEqual(quality["status"], "DEGRADED")
        self.assertIn("SOURCE_TIME_BASIS_UNVERIFIED", quality["flags"])
        self.assertNotIn("FUTURE_SOURCE_TIMESTAMP", quality["flags"])
        self.assertIsNone(quality["tick_age_seconds"])
        self.assertEqual(quality["candle_age_seconds"], 230)

    def test_explicit_utc_basis_normalizes_source_and_calculates_distinct_ages(self):
        observed = datetime(2026, 9, 23, 9, 24, tzinfo=timezone.utc)
        tick = observed - timedelta(seconds=4)
        bar = tick - timedelta(seconds=230)
        provenance = normalize_mt5_epoch(bar.timestamp(), "UTC")
        tick_meta = normalize_mt5_epoch(tick.timestamp(), "UTC")
        quality = _quality({"source_timestamp": provenance["normalized_utc"],
            "time_provenance": {"normalization_status": "VERIFIED"},
            "backend_received_at": (observed - timedelta(seconds=1)).isoformat(),
            "tick_age_seconds": 4, "candle_age_seconds": 230}, observed.isoformat())
        self.assertEqual(provenance["normalization_status"], "VERIFIED")
        self.assertEqual(tick_meta["normalized_utc"], tick.isoformat())
        self.assertEqual(quality["tick_age_seconds"], 4)
        self.assertEqual(quality["candle_age_seconds"], 230)
        self.assertEqual(quality["observation_latency_seconds"], 1)

    def test_naive_source_timestamp_cannot_pass_verified_quality(self):
        observed = "2026-09-23T09:24:00+00:00"
        quality = _quality({"source_timestamp": "2026-09-23T09:23:00",
            "time_provenance": {"timezone_normalization_status": "VERIFIED"},
            "backend_received_at": observed}, observed)
        self.assertEqual(quality["status"], "DEGRADED")
        self.assertIn("INVALID_SOURCE_TIMESTAMP", quality["flags"])

    def test_explicit_iana_timezone_normalizes_without_fixed_offset(self):
        try:
            ZoneInfo("Africa/Nairobi")
        except ZoneInfoNotFoundError:
            self.skipTest("IANA tz database is unavailable; implementation must keep this basis invalid/degraded")
        wall_epoch = datetime(2026, 9, 23, 12, 15, tzinfo=timezone.utc).timestamp()
        result = normalize_mt5_epoch(wall_epoch, "Africa/Nairobi")
        self.assertEqual(result["normalization_status"], "VERIFIED")
        self.assertEqual(result["normalized_utc"], "2026-09-23T09:15:00+00:00")
        self.assertEqual(result["raw_mt5_epoch"], wall_epoch)

    def test_dst_ambiguous_and_nonexistent_wall_times_are_not_guessed(self):
        try:
            ZoneInfo("Europe/London")
        except ZoneInfoNotFoundError:
            self.skipTest("IANA tz database is unavailable")
        ambiguous_wall_epoch = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc).timestamp()
        nonexistent_wall_epoch = datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc).timestamp()
        ambiguous = normalize_mt5_epoch(ambiguous_wall_epoch, "Europe/London")
        nonexistent = normalize_mt5_epoch(nonexistent_wall_epoch, "Europe/London")
        self.assertEqual(ambiguous["normalization_status"], "UNVERIFIED")
        self.assertEqual(nonexistent["normalization_status"], "INVALID")

    def test_canonical_parser_normalizes_aware_offsets_and_rejects_naive(self):
        parsed = parse_aware_utc("2026-09-23T12:00:00+03:00")
        self.assertEqual(parsed, datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc))
        self.assertIsNone(parse_aware_utc("2026-09-23T12:00:00"))

    def test_unverified_basis_never_converts_to_utc(self):
        result = normalize_mt5_epoch(1790165700, "UNKNOWN_ZONE")
        self.assertEqual(result["normalization_status"], "UNVERIFIED")
        self.assertIsNone(result["normalized_utc"])

    def test_source_clock_is_verified_only_when_both_bar_and_quote_are_verified(self):
        verified = {"normalization_status": "VERIFIED"}
        unverified = {"normalization_status": "UNVERIFIED"}
        invalid = {"normalization_status": "INVALID"}
        self.assertEqual(combined_normalization_status(verified, verified), "VERIFIED")
        self.assertEqual(combined_normalization_status(verified, unverified), "UNVERIFIED")
        self.assertEqual(combined_normalization_status(verified, invalid), "INVALID")

    def test_snapshot_preserves_raw_epoch_and_three_distinct_time_concepts(self):
        received = "2026-09-23T09:23:59+00:00"
        observed = "2026-09-23T09:24:01+00:00"
        raw_bar, raw_tick = 1790165700, 1790165939.5
        market = {"symbol": "XAUUSD", "timeframe": "M15", "direction": "LONG",
            "price": 4000, "source_timestamp": None, "backend_received_at": received,
            "tick_age_seconds": None, "candle_age_seconds": 239.5,
            "time_provenance": {"bar_open_time": {"raw_mt5_epoch": raw_bar,
                "normalization_status": "UNVERIFIED"}, "tick_time": {
                "raw_mt5_epoch": raw_tick, "normalization_status": "UNVERIFIED"},
                "backend_received_at": received, "raw_mt5_tick_time_msc": 1790165939500,
                "source_time_basis": "UNVERIFIED",
                "timezone_normalization_status": "UNVERIFIED"}}
        row = _snapshot(market, "stp", "DETECTED", observed)
        self.assertEqual(row["time_provenance"]["bar_open_time"]["raw_mt5_epoch"], raw_bar)
        self.assertEqual(row["time_provenance"]["tick_time"]["raw_mt5_epoch"], raw_tick)
        self.assertEqual(row["observed_at"], observed)
        self.assertEqual(row["time_provenance"]["backend_received_at"], received)
        self.assertEqual(row["time_provenance"]["backend_observation_time"], observed)
        self.assertEqual(row["time_provenance"]["observation_time"], observed)
        self.assertEqual(row["time_provenance"]["raw_mt5_tick_time_msc"], 1790165939500)
        self.assertEqual(row["data_quality"]["candle_age_seconds"], 239.5)
        self.assertIsNone(row["data_quality"]["tick_age_seconds"])

    def test_legacy_utc_converter_remains_host_independent(self):
        epoch = datetime(2026, 9, 23, 12, 15, tzinfo=timezone.utc).timestamp()
        self.assertEqual(mt5_epoch_to_utc_iso(epoch), "2026-09-23T12:15:00+00:00")

    def test_analyst_explicitly_warns_when_source_time_is_untrusted(self):
        result = analyze_snapshot({"setup_id": "s", "observation_id": "o", "direction": "SHORT",
            "rule_evidence": {"strategy_valid": False}, "features": {},
            "data_quality": {"status": "DEGRADED", "flags": ["SOURCE_TIME_BASIS_UNVERIFIED"]}},
            "2026-09-23T12:00:00Z")
        self.assertIn("untrusted", result["summary"])


if __name__ == "__main__":
    unittest.main()
