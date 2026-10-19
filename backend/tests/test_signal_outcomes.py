"""T-032 Phase 4: authoritative signal outcomes (chronology, M1 tie-break, recovery, audit trail)."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import signal_outcomes as so

T0 = datetime(2026, 10, 5, 10, 7, 30, tzinfo=timezone.utc)      # confirmation inside the 10:00 M15 candle
BAR0 = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc).timestamp()
LONG = {"direction": "LONG", "entry": 100.0, "stop_loss": 99.0, "take_profit": 102.0}
SHORT = {"direction": "SHORT", "entry": 100.0, "stop_loss": 101.0, "take_profit": 98.0}


def m15(n=40, high=100.5, low=99.5, spread=0.0, overrides=None):
    bars = [{"utc": BAR0 + 900 * k, "open": 100.0, "high": high, "low": low, "close": 100.0, "spread": spread} for k in range(n)]
    for k, values in (overrides or {}).items():
        bars[k].update(values)
    return bars


def m1(start, minutes, high=100.5, low=99.5, overrides=None, spread=0.0):
    bars = [{"utc": start + 60 * k, "open": 100.0, "high": high, "low": low, "close": 100.0, "spread": spread} for k in range(minutes)]
    for k, values in (overrides or {}).items():
        bars[k].update(values)
    return bars


NOW = T0 + timedelta(days=10)


class ResolveTests(unittest.TestCase):
    def test_target_then_stop_in_order(self):
        result = so.resolve(LONG, T0, m15(overrides={3: {"high": 102.2}, 5: {"low": 98.5}}), None, NOW)
        self.assertEqual(result["status"], "TARGET_HIT")
        self.assertEqual(result["r_multiple"], 2.0)
        self.assertEqual(result["hit_at"], datetime.fromtimestamp(BAR0 + 900 * 3, timezone.utc).isoformat())

    def test_stop_first(self):
        result = so.resolve(LONG, T0, m15(overrides={2: {"low": 98.9}, 4: {"high": 103}}), None, NOW)
        self.assertEqual((result["status"], result["r_multiple"]), ("STOP_HIT", -1.0))

    def test_sell_exits_at_the_ask(self):
        # Bid high 100.95 + spread 0.1 reaches the 101 stop of a SELL; bid-only would miss it.
        bars = m15(spread=0.1, overrides={2: {"high": 100.95}, 4: {"low": 97.5}})
        self.assertEqual(so.resolve(SHORT, T0, bars, None, NOW)["status"], "STOP_HIT")
        # The target needs the ASK at 98: a bid low of 97.95 with 0.1 spread is not enough.
        bars = m15(spread=0.1, overrides={2: {"low": 97.95}, 3: {"low": 97.8}})
        result = so.resolve(SHORT, T0, bars, None, NOW)
        self.assertEqual(result["hit_at"], datetime.fromtimestamp(BAR0 + 900 * 3, timezone.utc).isoformat())

    def test_both_levels_in_one_candle_use_m1(self):
        bars = m15(overrides={4: {"high": 102.5, "low": 98.5}})
        start = BAR0 + 900 * 4
        minutes = m1(BAR0 - 60, 30) + m1(start, 15, overrides={6: {"low": 98.8}, 9: {"high": 102.4}})
        result = so.resolve(LONG, T0, bars, minutes, NOW)
        self.assertEqual((result["status"], result["method"]), ("STOP_HIT", "M1"))

    def test_both_levels_without_m1_or_in_one_minute_are_ambiguous(self):
        bars = m15(overrides={4: {"high": 102.5, "low": 98.5}})
        self.assertEqual(so.resolve(LONG, T0, bars, None, NOW)["status"], "AMBIGUOUS")
        start = BAR0 + 900 * 4
        minutes = m1(BAR0 - 60, 30) + m1(start, 15, overrides={3: {"low": 98.8, "high": 102.4}})
        self.assertEqual(so.resolve(LONG, T0, bars, minutes, NOW)["status"], "AMBIGUOUS")

    def test_confirmation_candle_before_confirmation_is_ignored(self):
        # The 10:00 candle dipped to the stop at 10:02, before the 10:07:30 confirmation: not a stop.
        bars = m15(overrides={0: {"low": 98.5}, 3: {"high": 102.5}})
        minutes = m1(BAR0, 30, overrides={2: {"low": 98.5}})
        result = so.resolve(LONG, T0, bars, minutes, NOW)
        self.assertEqual(result["status"], "TARGET_HIT")
        # ...but a stop at 10:12, after the confirmation, inside the same candle counts.
        minutes = m1(BAR0, 30, overrides={12: {"low": 98.5}})
        result = so.resolve(LONG, T0, bars, minutes, NOW)
        self.assertEqual((result["status"], result["method"]), ("STOP_HIT", "M1"))

    def test_confirmation_candle_without_m1(self):
        # Whole candle inside both levels: the remainder cannot have touched either.
        self.assertEqual(so.resolve(LONG, T0, m15(overrides={3: {"high": 102.5}}), None, NOW)["status"], "TARGET_HIT")
        # Candle touched a level and its minutes are unknown: unavailable, never guessed.
        result = so.resolve(LONG, T0, m15(overrides={0: {"low": 98.5}}), None, NOW)
        self.assertEqual(result["status"], "UNAVAILABLE")

    def test_open_window_and_expiry(self):
        quiet = m15(n=10)
        self.assertEqual(so.resolve(LONG, T0, quiet, None, T0 + timedelta(hours=2))["status"], "PENDING")
        week = m15(n=7 * 96 + 4)
        self.assertEqual(so.resolve(LONG, T0, week, None, T0 + timedelta(days=8))["status"], "NO_HIT")

    def test_inconsistent_or_missing_plan_is_unavailable(self):
        for plan in ({"direction": "LONG", "entry": 100, "stop_loss": 101, "take_profit": 102},
                     {"direction": "SHORT", "entry": 100, "stop_loss": None, "take_profit": 98}, {}):
            self.assertEqual(so.resolve(plan, T0, m15(), None, NOW)["status"], "UNAVAILABLE")

    def test_missing_history_is_unavailable(self):
        self.assertEqual(so.resolve(LONG, T0, [], None, NOW)["status"], "UNAVAILABLE")


class StoreAndRecoveryTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.path = Path(self._temp.name) / "signal_outcomes.jsonl"

    def tearDown(self):
        self._temp.cleanup()

    def confirmation(self):
        return {"setup_id": "stp_x", "observation_id": "obs_x", "confirmation_event_id": "cnf_x",
                "confirmed_at": T0.isoformat(), "symbol": "EURUSD", "strategy_id": "trendline_v5", "score": 80}

    def snapshot(self):
        return {"observation_id": "obs_x", "broker_symbol": "EURUSD", "timeframe": "M15", "direction": "LONG",
                "proposed_entry": 100.0, "proposed_stop_loss": 99.0, "proposed_take_profit": 102.0}

    def test_downtime_recovery_progress_and_audit_trail(self):
        calls = []
        bars = {"M15": m15(n=10)}

        def fetch(symbol, timeframe, start, end):
            calls.append((symbol, timeframe))
            if bars.get("offline"):
                return None
            return [b for b in bars.get(timeframe, []) if b["utc"] <= end.timestamp()]

        clock = {"now": T0 + timedelta(hours=2)}
        resolver = so.Resolver(fetch, so.OutcomeStore(self.path), clock=lambda: clock["now"])
        snap = self.snapshot()
        self.assertEqual(resolver.run([self.confirmation()], {"obs_x": snap}.get), 1)
        self.assertEqual(resolver.store.latest("stp_x")["status"], "PENDING")
        # Unchanged: no duplicate revision.
        self.assertEqual(resolver.run([self.confirmation()], {"obs_x": snap}.get), 0)
        # MT5 offline: nothing is written or guessed.
        bars["offline"] = True
        clock["now"] = T0 + timedelta(days=3)
        self.assertEqual(resolver.run([self.confirmation()], {"obs_x": snap}.get), 0)
        # Engine back after downtime: the full path is fetched and the hit recovered.
        bars.pop("offline")
        bars["M15"] = m15(n=300, overrides={150: {"high": 102.3}})
        self.assertEqual(resolver.run([self.confirmation()], {"obs_x": snap}.get), 1)
        final = resolver.store.latest("stp_x")
        self.assertEqual((final["status"], final["revision"], final["correction_reason"]), ("TARGET_HIT", 2, "progressed"))
        self.assertEqual(final["supersedes"], resolver.store.history("stp_x")[0]["outcome_id"])
        # Final outcomes are not re-fetched, and survive a restart (reloaded from disk).
        before = len(calls)
        restarted = so.Resolver(fetch, so.OutcomeStore(self.path), clock=lambda: clock["now"])
        self.assertEqual(restarted.run([self.confirmation()], {"obs_x": snap}.get), 0)
        self.assertEqual(len(calls), before)
        self.assertEqual(restarted.store.latest("stp_x")["status"], "TARGET_HIT")
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        self.assertEqual([row["status"] for row in rows], ["PENDING", "TARGET_HIT"])

    def test_correction_of_a_final_outcome_is_a_new_revision(self):
        store = so.OutcomeStore(self.path)
        base = {"setup_id": "stp_y"}
        store.write(base, {"status": "AMBIGUOUS", "hit_at": None, "r_multiple": None, "reason": "no M1"})
        self.assertIsNone(store.write(base, {"status": "PENDING", "hit_at": None, "r_multiple": None, "reason": "x"}))
        row = store.write(base, {"status": "STOP_HIT", "hit_at": "t", "r_multiple": -1.0, "reason": "M1 replay"},
                          correction_reason="M1 history recovered")
        self.assertEqual((row["revision"], row["correction_reason"]), (2, "M1 history recovered"))
        self.assertEqual(len(so.OutcomeStore(self.path).history("stp_y")), 2)

    def test_missing_snapshot_is_unavailable(self):
        resolver = so.Resolver(lambda *a: [], so.OutcomeStore(self.path), clock=lambda: NOW)
        resolver.run([self.confirmation()], {}.get)
        self.assertEqual(resolver.store.latest("stp_x")["status"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
