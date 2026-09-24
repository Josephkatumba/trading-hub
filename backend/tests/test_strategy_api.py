"""Phase 4: strategy-aware API plumbing (additive only).

The radar response gains `strategy_registry` (which strategies are LIVE), a
`/api/market/strategies` route lists the registry, episodes expose strategy_id
(read-time mapped for historical records), and all existing fields stay as they
were. The confirmed bucket is decided by the confirmation event and lifecycle
state, never by the latest snapshot.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g  # noqa: E402

import legacy_observations as legacy  # noqa: E402
import main  # noqa: E402
import observations  # noqa: E402
import strategies  # noqa: E402
from strategies import Strategy  # noqa: E402
from test_strategy_isolation import IsolationTestCase, market  # noqa: E402

RADAR_KEYS = {"source", "live", "markets", "timestamp", "engine_status", "mt5_status", "error"}


class Disabled(Strategy):
    strategy_id, version, timeframe, lifecycle = "smc", "smc-v0", "M15", "smc"

    def evaluate(self, market):
        raise AssertionError("a disabled strategy must never run")


class RegistryApiTests(unittest.TestCase):
    def test_describe_lists_status_for_every_registered_strategy(self):
        self.assertEqual(strategies.REGISTRY.describe(), [
            {"strategy_id": "trendline", "version": "trendline-first-v4", "timeframe": "M15", "higher_timeframes": ["H1"], "status": "LIVE"},
            {"strategy_id": "support_resistance", "version": "sr-levels-v1", "timeframe": "M15",
             "higher_timeframes": ["H1", "H4", "D1"], "status": "SHADOW"},
            {"strategy_id": "trend_momentum", "version": "tm-pullback-v1", "timeframe": "M15",
             "higher_timeframes": ["H1", "H4", "D1"], "status": "SHADOW"}])
        registry = strategies.build_default_registry()
        registry.register(Disabled())
        self.assertEqual([(s["strategy_id"], s["status"]) for s in registry.describe()],
                         [("trendline", "LIVE"), ("support_resistance", "SHADOW"), ("trend_momentum", "SHADOW"), ("smc", "DISABLED")])

    def test_radar_response_adds_the_registry_and_keeps_every_existing_field(self):
        with mock.patch.object(main, "market_snapshot", return_value=[]):
            response = main.radar()
        self.assertEqual(set(response) - {"strategy_registry"}, RADAR_KEYS)
        self.assertEqual(response["strategy_registry"], strategies.REGISTRY.describe())
        registry = strategies.build_default_registry()
        registry.register(Disabled())
        with mock.patch.object(main, "market_snapshot", return_value=[]), mock.patch.object(main, "STRATEGIES", registry):
            self.assertEqual([s["status"] for s in main.radar()["strategy_registry"]], ["LIVE", "SHADOW", "SHADOW", "DISABLED"])
            self.assertEqual([s["strategy_id"] for s in main.strategy_registry()["strategies"]], ["trendline", "support_resistance", "trend_momentum", "smc"])


class EpisodeApiTests(IsolationTestCase):
    def feed(self, bucket):
        with g.isolated_store(observations, self.store.root):
            return main.setup_episode_feed(bucket=bucket, limit=100)

    def test_episodes_expose_strategy_id_for_new_and_historical_records(self):
        self.store.scan(market("LONG"), market("SHORT", "smc", anchors=None))
        rows = self.feed("current")["episodes"]
        self.assertEqual(sorted(r["strategy_id"] for r in rows), ["smc", "trendline"])
        with tempfile.TemporaryDirectory() as tmp:
            files = g.run_persistence(legacy, Path(tmp))      # written before strategy_id existed
            for name, data in files.items():
                (self.store.root / name).write_bytes(data)
        all_rows = self.feed("all")
        historical = all_rows["current"] + all_rows["confirmed"] + all_rows["closed"]
        self.assertTrue(historical)
        self.assertEqual({r["strategy_id"] for r in historical}, {"trendline"})
        self.assertTrue(all("strategy_id" not in json.loads(line) for line in files["setup_observations.jsonl"].splitlines()))

    def test_confirmed_bucket_follows_the_confirmation_not_the_latest_snapshot(self):
        # Confirm a trendline setup, then keep observing it as directional context.
        confirmed = market("LONG", state="CONFIRMING", valid=True, invalidation=2600.0)
        setup_id = self.store.scan(confirmed)[0]["setup_id"]
        context = {**market("LONG", context=True, state="WATCHING"), "trendline_gate": False}
        followed = self.store.scan(context)[0]
        self.assertEqual(followed["setup_id"], setup_id, "context observation continued the confirmed episode")
        rows = {r["setup_id"]: r for r in self.feed("all")["confirmed"]}
        row = rows[setup_id]
        self.assertEqual(row["setup_type"], "WATCHING")                   # latest market observation
        self.assertEqual(row["confirmation"]["setup_type"], "BREAK")      # historical confirmation event
        self.assertIn(row["lifecycle_state"], {"CONFIRMED", "ACTIVE"})    # setup lifecycle state
        self.assertEqual(row["bucket"], "confirmed")


if __name__ == "__main__":
    unittest.main()
