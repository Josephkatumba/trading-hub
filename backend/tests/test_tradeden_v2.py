"""TRADEden V2 audit fixes.

- qualification: a confirmed setup is re-checked at the executable price (ask for LONG,
  bid for SHORT): stop/target on the right sides, price not yet past either, executable
  R:R (spread paid) >= 1.5. A failing setup is not confirmed; nothing is re-planned.
- lifecycle: an unconfirmed setup the strategy stops reporting is EXPIRED
  (SIGNAL_WITHDRAWN), not INVALIDATED; stored withdrawals read as such.
- outcomes: a path is labelled only when the bars reach back to the observation.
- performance: verified figures follow the Strategy Lab rule and always reconcile.
- storage: a line damaged on disk (non-UTF-8 bytes) is skipped, never fatal.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import qualification  # noqa: E402
from outcomes import derive_market_outcome
from episode_identity import (CONFIRMED_EVENTS_LIFECYCLE, SIGNAL_WITHDRAWN, closure_kind,  # noqa: E402
                              rank_candidates, withdrawn_invalidation)
from outcomes import list_records, resolve_due_market_outcomes  # noqa: E402
from performance import performance_report, verified_summary  # noqa: E402
import observations  # noqa: E402


def setup(direction="LONG", entry=100.0, stop=98.0, target=104.0, bid=100.0, ask=100.02, valid=True):
    return {"direction": direction, "entry": entry, "stop_loss": stop, "take_profit": target,
            "bid": bid, "ask": ask, "strategy_valid": valid, "reason": "rules met", "tick_age_seconds": 1.2}


class QualificationTests(unittest.TestCase):
    def test_manual_derivation_rejects_truncated_start(self):
        observed = datetime(2026, 1, 1, tzinfo=timezone.utc)
        snapshot = {"setup_id": "s", "observation_id": "o", "observed_at": observed.isoformat(),
                    "source_timestamp": observed.isoformat(), "reference_price": 100, "direction": "LONG",
                    "time_provenance": {"timezone_normalization_status": "VERIFIED"}}
        bars = [{"time": (observed + timedelta(minutes=m)).timestamp(), "high": 101, "low": 99, "close": 100}
                for m in (30, 45)]
        self.assertIsNone(derive_market_outcome(snapshot, "1h", bars, "M15",
                                             now=observed + timedelta(hours=2)))

    def test_a_good_setup_stays_confirmed_and_records_the_executable_rr(self):
        market = qualification.apply(setup())
        self.assertTrue(market["strategy_valid"])
        self.assertNotIn("strategy_signal_valid", market)
        q = market["qualification"]
        self.assertTrue(q["qualified"])
        self.assertEqual(q["executable_price"], 100.02)                  # LONG buys at the ask
        self.assertAlmostEqual(q["executable_rr"], (104 - 100.02) / (100.02 - 98), places=4)

    def test_the_spread_can_take_a_setup_below_the_minimum(self):
        # 1.5R from the close, but paying a wide spread leaves less than 1.5R.
        market = qualification.apply(setup(stop=98.0, target=103.0, bid=100.0, ask=100.3))
        self.assertFalse(market["strategy_valid"])
        self.assertTrue(market["strategy_signal_valid"])
        self.assertEqual(market["qualification"]["failed"], ["min_rr"])
        self.assertIn("not qualified at the executable price", market["reason"])

    def test_price_already_past_the_stop_or_target_is_not_a_confirmation(self):
        past_stop = qualification.apply(setup(bid=97.9, ask=97.92))
        past_target = qualification.apply(setup(direction="SHORT", entry=100, stop=102, target=96, bid=95.9, ask=95.95))
        for market in (past_stop, past_target):
            self.assertFalse(market["strategy_valid"])
            self.assertIn("inside_barriers", market["qualification"]["failed"])

    def test_short_uses_the_bid_and_exits_at_the_ask(self):
        q = qualification.qualify(setup(direction="SHORT", entry=100, stop=102, target=96, bid=99.98, ask=100.0))
        self.assertEqual(q["executable_price"], 99.98)
        self.assertAlmostEqual(q["executable_rr"], (99.98 - 96) / (102 - 99.98), places=4)

    def test_unconfirmed_setups_are_never_promoted_and_no_quote_fails_closed(self):
        self.assertFalse(qualification.apply(setup(valid=False, ask=100.0))["strategy_valid"])
        no_quote = qualification.apply(setup(bid=None, ask=None))
        self.assertFalse(no_quote["strategy_valid"])
        self.assertIn("quote_available", no_quote["qualification"]["failed"])

    def test_the_threshold_uses_the_unrounded_ratio(self):
        # 1.4975R would round to 1.5 at two decimals; it does not qualify.
        q = qualification.qualify(setup(stop=98.0, target=102.995, bid=100.0, ask=100.0))
        self.assertLess(q["executable_rr"], 1.5)
        self.assertFalse(q["qualified"])

    def test_a_stale_or_unverified_quote_cannot_confirm(self):
        for age in (None, 38 * 3600, -60):
            market = qualification.apply({**setup(), "tick_age_seconds": age})
            self.assertFalse(market["strategy_valid"], age)
            self.assertEqual(market["qualification"]["failed"], ["quote_fresh"])

    def test_markets_without_direction_are_left_alone(self):
        market = {"direction": None, "strategy_valid": False}
        self.assertEqual(qualification.apply(dict(market)), market)


class WithdrawalTests(unittest.TestCase):
    NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)

    def candidate(self, state="DETECTED"):
        return {"setup_id": "stp_a", "symbol": "EURUSD", "timeframe": "M15", "direction": "LONG",
                "lifecycle_state": state, "reference_price": 1.1, "invalidation_price": 1.09,
                "observed_at": (self.NOW - timedelta(minutes=15)).isoformat(), "setup_type": "REVERSAL"}

    def test_a_direction_change_expires_an_unconfirmed_setup_as_withdrawn(self):
        market = {"symbol": "EURUSD", "timeframe": "M15", "direction": "SHORT", "price": 1.1005, "atr": 0.001}
        _, evaluated = rank_candidates(market, [self.candidate()], self.NOW, confirmed_events=True)
        self.assertEqual(evaluated[0][1:3], ("EXPIRE", SIGNAL_WITHDRAWN + ":DIRECTION_CHANGED"))

    def test_a_confirmed_setup_is_still_only_competing(self):
        market = {"symbol": "EURUSD", "timeframe": "M15", "direction": "SHORT", "price": 1.1005, "atr": 0.001}
        _, evaluated = rank_candidates(market, [self.candidate("ACTIVE")], self.NOW, confirmed_events=True)
        self.assertEqual(evaluated[0][1], "COMPETING")

    def test_price_crossing_the_invalidation_is_still_an_invalidation(self):
        market = {"symbol": "EURUSD", "timeframe": "M15", "direction": "SHORT", "price": 1.0899, "atr": 0.001}
        _, evaluated = rank_candidates(market, [self.candidate()], self.NOW, confirmed_events=True)
        self.assertEqual(evaluated[0][1:3], ("INVALIDATE", "INVALIDATION_PRICE_CROSSED"))

    def test_the_original_matcher_policy_is_unchanged(self):
        market = {"symbol": "EURUSD", "timeframe": "M15", "direction": "SHORT", "price": 1.1005, "atr": 0.001}
        _, evaluated = rank_candidates(market, [self.candidate()], self.NOW, confirmed_events=False)
        self.assertEqual(evaluated[0][1:3], ("INVALIDATE", "DIRECTION_CHANGED"))
        self.assertIn("confirmed-events", CONFIRMED_EVENTS_LIFECYCLE)

    def test_closure_kinds(self):
        legacy = {"to_state": "INVALIDATED", "reason_code": "DIRECTION_CHANGED"}
        self.assertTrue(withdrawn_invalidation(legacy))
        cases = {("INVALIDATED", "DIRECTION_CHANGED"): "WITHDRAWN",
                 ("EXPIRED", SIGNAL_WITHDRAWN + ":SETUP_FAMILY_CHANGED"): "WITHDRAWN",
                 ("INVALIDATED", "INVALIDATION_PRICE_CROSSED"): "PRICE_INVALIDATED",
                 ("RESOLVED", "TARGET_PRICE_CROSSED"): "TARGET_RESOLVED",
                 ("EXPIRED", "INACTIVITY_TIMEOUT"): "TIMED_OUT",
                 ("EXPIRED", "EPISODE_REPLACED:LEVEL_CHANGED"): "REPLACED",
                 ("ACTIVE", "SCANNER_STATE_CHANGED"): None}
        for (state, reason), kind in cases.items():
            self.assertEqual(closure_kind({"to_state": state, "reason_code": reason}), kind, (state, reason))


class OutcomeCoverageTests(unittest.TestCase):
    OBSERVED = datetime(2026, 10, 7, 10, 7, tzinfo=timezone.utc)

    def snapshot(self):
        return {"record_type": "setup_snapshot", "setup_id": "stp_c", "observation_id": "obs_c", "symbol": "EURUSD",
                "timeframe": "M15", "direction": "LONG", "reference_price": 1.1, "proposed_take_profit": 1.103,
                "invalidation_price": 1.098, "observed_at": self.OBSERVED.isoformat(),
                "source_timestamp": self.OBSERVED.isoformat(),
                "time_provenance": {"timezone_normalization_status": "VERIFIED", "source_time_basis": "UTC"},
                "rule_evidence": {"strategy_valid": True}}

    def bars(self, first_open):
        start = first_open.timestamp()
        return [{"time": start + i * 900, "open": 1.1, "high": 1.1005, "low": 1.0995, "close": 1.1} for i in range(40)]

    def resolve(self, bars):
        snapshot = self.snapshot()
        confirmation = {"setup_id": "stp_c", "observation_id": "obs_c", "symbol": "EURUSD"}
        return resolve_due_market_outcomes([confirmation], {"obs_c": snapshot}, {"EURUSD": bars}, [], ("1h",),
                                           now=self.OBSERVED + timedelta(hours=6))

    def test_bars_covering_the_observation_are_labelled(self):
        rows = self.resolve(self.bars(datetime(2026, 10, 7, 10, 0, tzinfo=timezone.utc)))
        self.assertEqual([row["label"] for row in rows], ["NO_HIT"])

    def test_a_window_starting_after_the_observation_is_not_labelled(self):
        # The first fetched bar opens 30 minutes after the observation: the start of the path is unknown.
        self.assertEqual(self.resolve(self.bars(datetime(2026, 10, 7, 10, 45, tzinfo=timezone.utc))), [])


class VerifiedPerformanceTests(unittest.TestCase):
    def outcome(self, sid, oid, horizon, label):
        stamp = "2026-10-07T10:30:00+00:00"
        return {"record_type": "market_outcome", "setup_id": sid, "observation_id": oid, "horizon": horizon,
                "label": label, "label_definition": "target-invalidation-first-v1", "timestamp_quality": "VERIFIED",
                "data_quality": {"timestamp_quality": "VERIFIED"}, "outcome_time_validity": "OUTCOME_TIME_VALID",
                "resolved_at": "2026-10-07T12:00:00+00:00",
                "outcome_time_validation": {"outcome_time_validity": "OUTCOME_TIME_VALID",
                                            "first_candidate_candle_timestamp": stamp,
                                            "last_candidate_candle_timestamp": stamp,
                                            "every_candidate_strictly_after_observation": True,
                                            "candidate_candles_chronological": True}}

    def snapshot(self, oid, rr=None):
        snap = {"observation_id": oid, "observed_at": "2026-10-07T10:07:00+00:00", "direction": "LONG",
                "reference_price": 100.0, "proposed_take_profit": 104.0, "invalidation_price": 98.0,
                "source_timestamp": "2026-10-07T10:07:00+00:00",
                "time_provenance": {"timezone_normalization_status": "VERIFIED"},
                "data_quality": {"timestamp_quality": "VERIFIED"}, "rule_evidence": {}}
        if rr is not None:
            snap["rule_evidence"]["qualification"] = {"executable_rr": rr}
        return snap

    def test_buckets_reconcile_and_r_uses_the_plan(self):
        events = [{"setup_id": f"stp_{i}", "observation_id": f"obs_{i}", "confirmed_at": "2026-10-07T10:07:00+00:00",
                   "strategy_id": "smc", "symbol": "EURUSD"} for i in range(4)]
        outcomes = [self.outcome("stp_0", "obs_0", "1h", "WIN"), self.outcome("stp_1", "obs_1", "15m", "LOSS"),
                    self.outcome("stp_2", "obs_2", "24h", "NO_HIT")]
        snapshots = {"obs_0": self.snapshot("obs_0"), "obs_1": self.snapshot("obs_1", rr=1.8),
                     "obs_2": self.snapshot("obs_2"), "obs_3": self.snapshot("obs_3")}
        report = performance_report(events, outcomes, [], report_date="2026-10-07", timezone_name="UTC",
                                    decision_snapshots=snapshots)
        verified = report["daily"][0]["verified"]
        self.assertTrue(verified["reconciled"])
        self.assertEqual((verified["confirmed"], verified["verified_target"], verified["verified_stop"],
                          verified["verified_other"], verified["pending"]), (4, 1, 1, 1, 1))
        self.assertEqual(verified["r"]["total_r"], 1.0)          # +2R (100 -> 104 vs 98) and -1R
        self.assertIsNone(verified["target_first_rate"])         # 2 decisive < 30: no rate
        self.assertEqual(report["daily"][0]["verified_by_strategy"]["smc"]["confirmed"], 4)

    def test_rates_appear_only_with_enough_decisive_outcomes(self):
        items = [{"kind": "verified_target", "r_multiple": 2.0}] * 20 + [{"kind": "verified_stop", "r_multiple": -1.0}] * 10
        summary = verified_summary(items)
        self.assertEqual(summary["target_first_rate"], 66.7)
        self.assertEqual(summary["r"]["average_r"], 1.0)
        self.assertEqual(summary["r"]["profit_factor"], 4.0)


class ScanQualificationTests(unittest.TestCase):
    """End to end through main._market_snapshot: the Trend / Momentum scenario confirms XAUUSD, but
    the fake broker's tick has no verified time, so the live qualification withholds it."""

    def test_an_unverified_quote_withholds_the_confirmation_and_records_why(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import json
        from unittest import mock
        import golden_support as g
        import main
        import tm_fixtures as f
        from strategies import build_default_registry
        from test_trend_momentum import ScenarioBroker
        broker = ScenarioBroker({"XAUUSD": f.scenario(symbol="XAUUSD")})
        main._MT5_SESSION.update(initialized=False, initializations=0)
        with tempfile.TemporaryDirectory() as tmp, g.isolated_store(observations, Path(tmp)),                 mock.patch.object(main, "mt5", broker), mock.patch.object(main, "datetime", g.FrozenClock.make()),                 mock.patch.object(main, "WATCHLIST", ["XAUUSD"]), mock.patch.object(main, "STRATEGIES", build_default_registry()),                 mock.patch.object(main, "resolve_due_market_outcomes", return_value=[]):
            try:
                markets = main.market_snapshot()
            finally:
                main._MT5_SESSION.update(initialized=False, initializations=0)
            confirmations = Path(tmp) / "setup_confirmations.jsonl"
            self.assertFalse(confirmations.exists() and confirmations.read_text().strip())
            snapshots = [json.loads(line) for line in (Path(tmp) / "setup_observations.jsonl").read_text().splitlines()]
        entry = {e["strategy_id"]: e for e in markets[0]["strategies"]}["trend_momentum"]
        self.assertEqual(entry["state"], "CONFIRMING")
        self.assertFalse(entry["confirmed"])
        self.assertIn("quote_fresh", entry["qualification"]["failed"])
        tm = [row for row in snapshots if row["strategy_id"] == "trend_momentum"][0]
        self.assertIs(tm["rule_evidence"]["strategy_signal_valid"], True)
        self.assertIs(tm["rule_evidence"]["strategy_valid"], False)
        self.assertEqual(tm["lifecycle_state"], "CONFIRMING")


class DamagedStoreTests(unittest.TestCase):
    def test_non_utf8_and_nul_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "store.jsonl"
            path.write_bytes(b'{"setup_id":"a"}\n\x00\x00\x00\xb0garbage\n{"setup_id":"b"}\n\x80\x91\n')
            self.assertEqual([row["setup_id"] for row in observations._read_jsonl(path)], ["a", "b"])
            self.assertEqual([row["setup_id"] for row in list_records(path)], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
