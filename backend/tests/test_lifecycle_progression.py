from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
import observations


def market(state="WATCHING", price=2650.0, valid=False):
    return {"symbol": "XAUUSD", "state": state, "direction": "LONG",
            "setup_family": "REVERSAL", "trendline_state": "REVERSAL",
            "timeframe": "M15", "price": price, "atr": 5.0,
            "invalidation_hint": 2635.0, "strategy_valid": valid,
            "score": 72, "rr": 2.0,
            "trendline_identity": {"orientation": "ASCENDING_SUPPORT", "anchors": [
                {"time": "a", "price": 2640}, {"time": "b", "price": 2645}]}}


class LifecycleProgressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = (observations.DATA_DIR, observations.LOG_FILE,
                    observations.LIFECYCLE_FILE, observations.CONFIRMATIONS_FILE)
        root = Path(self.temp.name)
        observations.DATA_DIR = root
        observations.LOG_FILE = root / "snapshots.jsonl"
        observations.LIFECYCLE_FILE = root / "lifecycle.jsonl"
        observations.CONFIRMATIONS_FILE = root / "confirmations.jsonl"

    def tearDown(self):
        (observations.DATA_DIR, observations.LOG_FILE,
         observations.LIFECYCLE_FILE, observations.CONFIRMATIONS_FILE) = self.old
        self.temp.cleanup()

    def record(self, row):
        observations.record_markets([row])
        return row.get("setup_id")

    def test_scanner_states_advance_through_confirmed_then_active_once(self):
        row = market()
        sid = self.record(row)
        self.assertEqual(observations.lifecycle_events(sid)[-1]["to_state"], "DETECTED")
        self.assertEqual(self.record(market("DEVELOPING")), sid)
        self.assertEqual(observations.lifecycle_events(sid)[-1]["to_state"], "DEVELOPING")
        self.assertEqual(self.record(market("CONFIRMING")), sid)
        self.assertEqual(observations.lifecycle_events(sid)[-1]["to_state"], "CONFIRMING")
        self.assertEqual(self.record(market("CONFIRMING", valid=True)), sid)
        self.assertEqual(observations.lifecycle_events(sid)[-1]["to_state"], "CONFIRMED")
        self.assertEqual(len(observations.confirmation_events(sid)), 1)
        self.assertEqual(self.record(market("CONFIRMING", valid=True)), sid)
        self.assertEqual(observations.lifecycle_events(sid)[-1]["to_state"], "ACTIVE")
        self.assertEqual(len(observations.confirmation_events(sid)), 1)
        buckets = observations.setup_episodes("all")
        self.assertEqual(buckets[0]["bucket"], "confirmed")

    def test_condition_break_invalidates_active_episode(self):
        row = market("CONFIRMING", valid=True)
        sid = self.record(row)
        self.record(market("CONFIRMING", valid=True))  # CONFIRMED -> ACTIVE
        observations.record_markets([market("NO SETUP", price=2630.0)])
        event = observations.lifecycle_events(sid)[-1]
        self.assertEqual((event["from_state"], event["to_state"]), ("ACTIVE", "INVALIDATED"))
        self.assertEqual(event["reason_code"], "INVALIDATION_PRICE_CROSSED")
        self.assertEqual(observations.setup_episodes("all")[0]["bucket"], "closed")

    def test_stale_active_episode_expires(self):
        row = market("CONFIRMING", valid=True)
        sid = self.record(row)
        self.record(market("CONFIRMING", valid=True))
        snapshots = observations.setup_history(sid)
        import json
        snapshots[-1]["observed_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        observations.LOG_FILE.write_text("".join(json.dumps(item) + "\n" for item in snapshots), encoding="utf-8")
        previous = os.environ.get("TRADING_HUB_EPISODE_MAX_GAP_SECONDS")
        os.environ["TRADING_HUB_EPISODE_MAX_GAP_SECONDS"] = "60"
        try:
            observations.record_markets([])
        finally:
            if previous is None:
                os.environ.pop("TRADING_HUB_EPISODE_MAX_GAP_SECONDS", None)
            else:
                os.environ["TRADING_HUB_EPISODE_MAX_GAP_SECONDS"] = previous
        event = observations.lifecycle_events(sid)[-1]
        self.assertEqual((event["from_state"], event["to_state"]), ("ACTIVE", "EXPIRED"))
        self.assertEqual(event["reason_code"], "INACTIVITY_TIMEOUT")


if __name__ == "__main__":
    unittest.main()
