from __future__ import annotations

import unittest
from datetime import datetime, timezone
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from episode_identity import evaluate_episode, identity_evidence, trendline_identity


def market(**overrides):
    value = {"symbol": "XAUUSD", "timeframe": "M15", "direction": "LONG",
             "setup_family": "REVERSAL", "price": 2650.0, "atr": 5.0,
             "trendline_identity": {"orientation": "ASCENDING_SUPPORT", "anchors": [
                 {"time": "2026-09-23T08:00:00Z", "price": 2640.0},
                 {"time": "2026-09-23T09:00:00Z", "price": 2645.0}]}}
    value.update(overrides)
    return value


class EpisodeIdentityTests(unittest.TestCase):
    def test_trendline_identity_is_stable_and_anchor_sensitive(self):
        first = trendline_identity(market())
        same = trendline_identity(market())
        changed = trendline_identity(market(trendline_identity={"orientation": "ASCENDING_SUPPORT", "anchors": [
            {"time": "2026-09-23T10:00:00Z", "price": 2650.0},
            {"time": "2026-09-23T11:00:00Z", "price": 2655.0}]}))
        self.assertEqual(first["fingerprint"], same["fingerprint"])
        self.assertNotEqual(first["fingerprint"], changed["fingerprint"])
        self.assertEqual(identity_evidence(market())["matcher_version"], "episode-match-v2")

    def test_same_episode_continues_within_price_and_time_tolerance(self):
        previous = {**market(), "setup_id": "stp_a", "observed_at": datetime.now(timezone.utc).isoformat(),
                    "reference_price": 2650.0, "episode_identity": identity_evidence(market()),
                    "invalidation_price": 2635.0, "lifecycle_state": "DETECTED"}
        decision, reason, _ = evaluate_episode(market(price=2651.0), previous, datetime.now(timezone.utc))
        self.assertEqual((decision, reason), ("CONTINUE", None))

    def test_distinct_geometry_and_significant_move_do_not_match(self):
        previous = {**market(), "setup_id": "stp_a", "observed_at": datetime.now(timezone.utc).isoformat(),
                    "reference_price": 2650.0, "episode_identity": identity_evidence(market()),
                    "invalidation_price": 2635.0}
        geometry = market(trendline_identity={"orientation": "ASCENDING_SUPPORT", "anchors": [
            {"time": "2026-09-23T10:00:00Z", "price": 2650.0},
            {"time": "2026-09-23T11:00:00Z", "price": 2655.0}]})
        self.assertEqual(evaluate_episode(geometry, previous, datetime.now(timezone.utc))[:2],
                         ("NO_MATCH", "TRENDLINE_GEOMETRY_CHANGED"))
        self.assertEqual(evaluate_episode(market(price=2670.0), previous, datetime.now(timezone.utc))[:2],
                         ("NO_MATCH", "SIGNIFICANT_PRICE_DISPLACEMENT"))

    def test_invalidation_and_inactivity_expire_episode(self):
        now = datetime.now(timezone.utc)
        previous = {**market(), "setup_id": "stp_a", "observed_at": now.isoformat(),
                    "reference_price": 2650.0, "invalidation_price": 2640.0,
                    "episode_identity": identity_evidence(market())}
        self.assertEqual(evaluate_episode(market(price=2639.0), previous, now)[:2],
                         ("INVALIDATE", "INVALIDATION_PRICE_CROSSED"))
        stale = {**previous, "observed_at": "2026-01-01T00:00:00+00:00"}
        self.assertEqual(evaluate_episode(market(), stale, now)[:2], ("EXPIRE", "INACTIVITY_TIMEOUT"))


if __name__ == "__main__":
    unittest.main()
