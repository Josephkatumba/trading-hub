"""trendline-first-v5 lifecycle: CONFIRMED_EVENTS_LIFECYCLE, reused from Trend / Momentum.

Every test runs the real observations.record_markets on a temporary store. The v5
tests patch a registry where v5 is the trendline (v5 is not registered in
production); the v4 / S/R / Trend-Momentum tests use the production registry.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support  # noqa: F401,E402  (puts backend on sys.path)

import observations  # noqa: E402
from episode_identity import CONFIRMED_EVENTS_LIFECYCLE, LEVEL_EPISODES_LIFECYCLE, MATCHER_VERSION  # noqa: E402
from strategies import (LIVE, StrategyRegistry, SupportResistanceStrategy, TrendMomentumStrategy,  # noqa: E402
                        TrendlineStrategy, build_default_registry)
from strategies.base import MarketInput  # noqa: E402
from strategies.trendline import TrendlineV5Strategy  # noqa: E402
from test_strategy_isolation import IsolationTestCase, market  # noqa: E402
from v5_fixtures import BASIS, forming_variants, h1_rows, m15_rows  # noqa: E402

STOP, PRICE = 2640.0, 2650.0          # market() puts the target at PRICE +/- 30


def v5_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(TrendlineV5Strategy(basis=BASIS), enabled=True, mode=LIVE)
    registry.register(SupportResistanceStrategy(), enabled=True, mode=LIVE)
    registry.register(TrendMomentumStrategy(), enabled=True, mode=LIVE)
    return registry


def tl(direction="LONG", **kwargs):
    """A live trendline market as main.market_snapshot stamps it (strategy_id trendline_v5)."""
    return market(direction, "trendline_v5", **kwargs)


def states(store, setup_id):
    return [e["to_state"] for e in store.events_for(setup_id)]


class V5LifecycleTestCase(IsolationTestCase):
    def setUp(self):
        super().setUp()
        self.registry = mock.patch.object(observations, "STRATEGIES", v5_registry())
        self.registry.start()

    def tearDown(self):
        self.registry.stop()
        super().tearDown()

    def confirm(self, direction="LONG"):
        stop = STOP if direction == "LONG" else PRICE + 10
        setup_id = self.store.scan(tl(direction, invalidation=stop))[0]["setup_id"]
        self.store.scan(tl(direction, state="CONFIRMING", valid=True, invalidation=stop))
        self.assertEqual(states(self.store, setup_id), ["DEVELOPING", "CONFIRMED"])
        return setup_id


class ConfirmedTrendlineLifecycleTests(V5LifecycleTestCase):
    def test_1_real_v5_output_reaches_confirmed(self):
        # Fixture seed 31: v5 confirms on closed bars with an H1 structural target >= 1.5R.
        full = m15_rows(31)
        closed = full[:-1]
        scan = TrendlineV5Strategy(basis=BASIS).evaluate(MarketInput("XAUUSD", closed + [forming_variants(closed[-1], 0.1)["flat"]], higher_rows=h1_rows(full)))
        self.assertTrue(scan["strategy_valid"])
        row = self.store.scan({**scan, "symbol": "XAUUSD", "price": scan["entry"], "timeframe": "M15", "strategy_id": "trendline_v5"})[0]
        self.assertEqual(states(self.store, row["setup_id"]), ["CONFIRMED"])
        confirmation = self.store.records("setup_confirmations.jsonl")
        self.assertEqual([c["setup_id"] for c in confirmation], [row["setup_id"]])

    def test_2_a_later_candle_colour_or_direction_change_does_not_close_it(self):
        setup_id = self.confirm("LONG")
        # Directional context from a bearish candle, then a SHORT trendline event: both competing.
        context = self.store.scan(tl("SHORT", context=True))[0]
        event = self.store.scan(tl("SHORT", invalidation=PRICE + 10))[0]
        self.assertEqual(states(self.store, setup_id), ["DEVELOPING", "CONFIRMED"])
        self.assertNotIn(setup_id, {context["setup_id"], event["setup_id"]})
        closing = [e for e in self.store.records("setup_lifecycle.jsonl") if e["setup_id"] == setup_id and e.get("reason_code") == "DIRECTION_CHANGED"]
        self.assertEqual(closing, [])

    def test_3_it_stays_open_and_becomes_active_until_a_legitimate_outcome(self):
        setup_id = self.confirm("LONG")
        self.store.scan(tl("LONG", state="CONFIRMING", valid=True, invalidation=STOP))
        self.assertEqual(states(self.store, setup_id)[-1], "ACTIVE")
        for direction in ("SHORT", "LONG", "SHORT", "SHORT"):             # candle-by-candle flips around the entry
            self.store.scan(tl(direction, context=True, price=PRICE + (2 if direction == "LONG" else -2)))
        self.assertEqual(states(self.store, setup_id), ["DEVELOPING", "CONFIRMED", "ACTIVE"])

    def test_4_target_hit_resolves_it(self):
        setup_id = self.confirm("LONG")
        self.store.scan(tl("SHORT", context=True))
        self.store.scan(tl("SHORT", context=True, price=PRICE + 30.5))       # through the confirmed target
        event = self.store.events_for(setup_id)[-1]
        self.assertEqual((event["to_state"], event["reason_code"]), ("RESOLVED", "TARGET_PRICE_CROSSED"))
        self.assertEqual(event["metadata"]["levels"], "confirmation")

    def test_5_stop_hit_invalidates_it(self):
        setup_id = self.confirm("SHORT")
        self.store.scan(tl("LONG", context=True))
        self.store.scan(tl("LONG", context=True, price=PRICE + 10.5))        # through the confirmed stop
        event = self.store.events_for(setup_id)[-1]
        self.assertEqual((event["to_state"], event["reason_code"]), ("INVALIDATED", "INVALIDATION_PRICE_CROSSED"))

    def test_6_the_confirmation_event_is_immutable(self):
        setup_id = self.confirm("LONG")
        before = self.store.records("setup_confirmations.jsonl")
        drifted = tl("LONG", state="CONFIRMING", valid=True, invalidation=STOP - 20, price=PRICE + 3)
        self.store.scan(drifted)
        self.store.scan(tl("SHORT", context=True))
        self.store.scan(tl("SHORT", context=True, price=STOP - 5))           # below the CONFIRMED stop, above the drifted one
        self.assertEqual(self.store.records("setup_confirmations.jsonl")[:len(before)], before)
        self.assertEqual([c["setup_id"] for c in self.store.records("setup_confirmations.jsonl")].count(setup_id), 1)
        self.assertEqual(self.store.events_for(setup_id)[-1]["reason_code"], "INVALIDATION_PRICE_CROSSED")

    def test_7_before_confirmation_a_direction_change_still_invalidates(self):
        first = self.store.scan(tl("LONG", invalidation=STOP))[0]
        self.store.scan(tl("LONG", state="CONFIRMING", invalidation=STOP))    # confirming, not confirmed
        self.store.scan(tl("SHORT", invalidation=PRICE + 10))
        event = self.store.events_for(first["setup_id"])[-1]
        self.assertEqual((event["to_state"], event["reason_code"]), ("INVALIDATED", "DIRECTION_CHANGED"))


class OtherStrategiesUnchangedTests(IsolationTestCase):
    def test_8_v4_is_retired_and_keeps_the_original_lifecycle(self):
        self.assertEqual(TrendlineStrategy.lifecycle, MATCHER_VERSION)
        self.assertEqual(TrendlineV5Strategy.lifecycle, CONFIRMED_EVENTS_LIFECYCLE)
        registry = build_default_registry()
        self.assertEqual(registry.get("trendline_v5").version, "trendline-first-v5.1")
        self.assertNotIn("trendline", registry.registered())
        # v4 records (strategy_id "trendline") still follow v4's lifecycle when v4 is pinned.
        with golden_support.v4_lineup(observations):
            first = self.store.scan(market("LONG", state="CONFIRMING", valid=True, invalidation=STOP))[0]
            self.store.scan(market("SHORT", invalidation=PRICE + 10))
        self.assertEqual(self.store.events_for(first["setup_id"])[-1]["reason_code"], "DIRECTION_CHANGED")

    def test_9_support_resistance_follows_its_level_lifecycle(self):
        # S/R's own policy (tests/test_sr_episodes.py): its other side is a competing
        # hypothesis, so a direction change no longer invalidates the open episode.
        self.assertEqual(SupportResistanceStrategy.lifecycle, LEVEL_EPISODES_LIFECYCLE)
        with mock.patch.object(observations, "STRATEGIES", v5_registry()):
            first = self.store.scan(market("LONG", "support_resistance", state="CONFIRMING", valid=True, invalidation=STOP))[0]
            self.store.scan(market("SHORT", "support_resistance", invalidation=PRICE + 10))
        self.assertNotIn("INVALIDATED", [e["to_state"] for e in self.store.events_for(first["setup_id"])])

    def test_10_trend_momentum_keeps_its_lifecycle(self):
        self.assertEqual(TrendMomentumStrategy.lifecycle, CONFIRMED_EVENTS_LIFECYCLE)
        registry = build_default_registry()
        self.assertEqual(registry.get("trend_momentum").lifecycle, CONFIRMED_EVENTS_LIFECYCLE)
        self.assertEqual(v5_registry().get("trend_momentum").version, registry.get("trend_momentum").version)


if __name__ == "__main__":
    unittest.main()
