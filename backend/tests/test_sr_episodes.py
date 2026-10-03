"""Support & Resistance episodes: LEVEL_EPISODES_LIFECYCLE and level-scoped suppression.

The live S/R scanner reports only its best candidate per symbol (nearest support LONG,
nearest resistance SHORT, or NO SETUP). Under the original matcher every change of that
report INVALIDATED the open episode, and the near-price terminal rule then suppressed
the symbol/direction for as long as price stayed within 3 ATR: S/R stopped producing
setups. These tests pin the fix:

- the other side / NO SETUP is a competing hypothesis, never a closure;
- a closed S/R episode suppresses only its own level, only when the MARKET ended it
  (stop / confirmed target), and only until a new test of that level;
- historical closures (no level closure record) suppress nothing and are never rewritten;
- no duplicates: one level + direction + test = one episode, whatever the scan cadence;
- strict confirmation is unchanged, and no strategy suppresses another.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jsonl_index  # noqa: E402
import observations  # noqa: E402
import strategies  # noqa: E402
from episode_identity import LEVEL_CLOSURE, LEVEL_EPISODES_LIFECYCLE, MATCHER_VERSION  # noqa: E402
from strategies import support_resistance as sr  # noqa: E402
from test_strategy_isolation import Store, market  # noqa: E402

BAR = 900.0
T0 = 1_790_000_000.0            # raw MT5 epoch of the last closed bar in round 0
SUPPORT = (2600.0, 2604.0)
RESISTANCE = (2640.0, 2644.0)


def sr_obs(direction="LONG", state="DEVELOPING", *, zone=None, price=None, bar=0, bars_ago=0, clean=True, valid=False,
           family="SR_BOUNCE", symbol="XAUUSD"):
    """An S/R market dict as main builds it (only the fields the episode code reads).
    `bar`: closed bars elapsed since T0; the touch happened `bars_ago` bars before the last closed bar."""
    long = direction == "LONG"
    if direction is None:
        return {"symbol": symbol, "timeframe": "M15", "direction": None, "state": "NO SETUP", "price": price or 2620.0,
                "atr": 2.0, "strategy_id": "support_resistance", "strategy_valid": False, "setup_family": None,
                "strategy_evidence": {"method": sr.STRATEGY_VERSION},
                "time_provenance": {"bar_open_time": {"raw_mt5_epoch": T0 + (bar + 1) * BAR}}}
    low, high = zone or (SUPPORT if long else RESISTANCE)
    price = price if price is not None else (high + 1.0 if long else low - 1.0)
    planned = state in {"DEVELOPING", "CONFIRMING"}
    stop = (low - 1.0) if long else (high + 1.0)
    target = (price + 12.0) if long else (price - 12.0)
    candle = T0 + bar * BAR
    return {"symbol": symbol, "timeframe": "M15", "direction": direction, "state": state, "price": price, "atr": 2.0,
            "strategy_id": "support_resistance", "strategy_version": sr.STRATEGY_VERSION, "strategy_valid": valid,
            "setup_family": family, "score": 60, "entry": price if planned else None,
            "stop_loss": stop if planned else None, "take_profit": target if planned else None,
            "invalidation_hint": stop if planned else None,
            "strategy_evidence": {"method": sr.STRATEGY_VERSION,
                                  "level": {"type": "SUPPORT" if long else "RESISTANCE", "price": (low + high) / 2,
                                            "zone_low": low, "zone_high": high},
                                  "touch": {"touched": state != "WATCHING", "bars_ago": bars_ago if state != "WATCHING" else None,
                                            "clean_test": clean and state != "WATCHING"},
                                  "rejection": {"candle_time": candle}},
            "time_provenance": {"bar_open_time": {"raw_mt5_epoch": candle + BAR}}}


def closures(store, setup_id):
    return [(e["to_state"], e["reason_code"]) for e in store.events_for(setup_id)
            if e["to_state"] in {"INVALIDATED", "EXPIRED", "RESOLVED"}]


def forget_process_state(root: Path) -> None:
    """A backend restart: drop in-memory indexes and episode tables for `root`."""
    for key in [key for key in jsonl_index._REGISTRY if Path(key[0]).parent == root.resolve()]:
        del jsonl_index._REGISTRY[key]
    observations._EPISODE_TABLES.clear()


class EpisodeTestCase(unittest.TestCase):
    full_path = False                # rerun every test on the full-row (non-indexed) episode path

    def setUp(self):
        self.store = Store()
        if self.full_path:
            patch = mock.patch.object(observations, "_episode_view", lambda: observations._FullEpisodeView())
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.store.close()

    def sr_ids(self):
        return {s["setup_id"] for s in self.store.records("setup_observations.jsonl") if s.get("strategy_id") == "support_resistance"}


class PolicyTests(unittest.TestCase):
    def test_sr_follows_the_level_policy_and_other_strategies_are_unchanged(self):
        self.assertEqual(strategies.SupportResistanceStrategy.lifecycle, LEVEL_EPISODES_LIFECYCLE)
        self.assertTrue(observations._level_episodes_policy("support_resistance"))
        self.assertTrue(observations._confirmed_events_policy("support_resistance"))
        for other in (strategies.TRENDLINE, "trend_momentum"):
            self.assertFalse(observations._level_episodes_policy(other))
        self.assertEqual(strategies.TrendlineStrategy.lifecycle, MATCHER_VERSION)

    def test_confirmation_rules_and_thresholds_are_unchanged(self):
        self.assertEqual(sr.CONFIRMATION_RULES, ("touched", "clean_test", "held", "rejection", "momentum",
                                                 "not_chasing", "stop_ok", "target", "min_rr", "pattern"))   # pattern: sr-levels-v2
        self.assertEqual(sr.CONFIRMATION_RULES_V1, sr.CONFIRMATION_RULES[:-1])
        self.assertEqual((sr.MIN_RR, sr.REJECTION_CLOSE_POSITION, sr.TEST_DISTANCE_ATR_H1, sr.MAX_CHASE_ATR_H1),
                         (1.5, 0.6, 1.0, 1.0))


class CompetingHypothesisTests(EpisodeTestCase):
    def test_flipping_sides_never_invalidates_and_never_duplicates(self):
        # Price sits between a support (2600-2604) and a nearby resistance (2606-2609): the
        # scanner's best candidate flips side from scan to scan while price barely moves.
        rounds = [self.store.scan(sr_obs("LONG", "WATCHING", bar=i) if i % 2 == 0 else
                                  sr_obs("SHORT", "WATCHING", zone=(2606.0, 2609.0), bar=i))[0] for i in range(12)]
        longs = {r["setup_id"] for r in rounds[0::2]}
        shorts = {r["setup_id"] for r in rounds[1::2]}
        self.assertEqual((len(longs), len(shorts)), (1, 1), "one episode per level and direction")
        self.assertFalse(any(r.get("episode_suppressed") for r in rounds))
        for setup_id in longs | shorts:
            self.assertEqual(closures(self.store, setup_id), [])

    def test_no_setup_scans_leave_the_episode_open(self):
        first = self.store.scan(sr_obs("LONG", "WATCHING"))[0]
        for bar in range(1, 4):
            self.store.scan(sr_obs(None, bar=bar, price=2606.0))
        again = self.store.scan(sr_obs("LONG", "DEVELOPING", bar=4))[0]
        self.assertEqual(again["setup_id"], first["setup_id"])
        self.assertEqual(again["lifecycle_state"], "DEVELOPING")
        self.assertEqual(closures(self.store, first["setup_id"]), [])

    def test_family_label_on_the_same_level_continues_the_episode(self):
        first = self.store.scan(sr_obs("LONG", "DEVELOPING", family="SR_BREAK_RETEST"))[0]
        second = self.store.scan(sr_obs("LONG", "DEVELOPING", family="SR_BOUNCE", bar=1, bars_ago=1))[0]
        self.assertEqual(second["setup_id"], first["setup_id"])

    def test_a_new_level_replaces_an_unconfirmed_episode(self):
        first = self.store.scan(sr_obs("LONG", "DEVELOPING"))[0]
        other = self.store.scan(sr_obs("LONG", "DEVELOPING", zone=(2610.0, 2612.0), price=2613.0, bar=1))[0]
        self.assertNotEqual(other["setup_id"], first["setup_id"])
        self.assertEqual(closures(self.store, first["setup_id"]), [("EXPIRED", "EPISODE_REPLACED:LEVEL_CHANGED")])
        self.assertFalse(other.get("episode_suppressed"))

    def test_price_leaving_an_unconfirmed_level_expires_it(self):
        first = self.store.scan(sr_obs("LONG", "WATCHING"))[0]
        self.store.scan(sr_obs(None, bar=1, price=2640.0))
        self.assertEqual(closures(self.store, first["setup_id"]), [("EXPIRED", "EPISODE_REPLACED:SIGNIFICANT_PRICE_DISPLACEMENT")])


class LifecycleTests(EpisodeTestCase):
    def test_progresses_through_the_whole_lifecycle_and_resolves_on_its_confirmed_target(self):
        first = self.store.scan(sr_obs("LONG", "WATCHING"))[0]
        self.store.scan(sr_obs("LONG", "DEVELOPING", bar=1))
        confirmed = self.store.scan(sr_obs("LONG", "CONFIRMING", bar=2, valid=True))[0]
        self.store.scan(sr_obs("LONG", "CONFIRMING", bar=3, valid=True))
        self.store.scan(sr_obs("SHORT", "WATCHING", zone=(2612.0, 2616.0), bar=4))   # the other side: competing
        self.store.scan(sr_obs(None, bar=5, price=2613.0))           # displaced, yet a confirmed setup stays open
        target = confirmed["take_profit"]
        self.store.scan(sr_obs(None, bar=6, price=target + 0.5))
        states = [e["to_state"] for e in self.store.events_for(first["setup_id"])]
        self.assertEqual(states, ["DETECTED", "DEVELOPING", "CONFIRMED", "ACTIVE", "RESOLVED"])
        self.assertEqual(self.store.events_for(first["setup_id"])[-1]["reason_code"], "TARGET_PRICE_CROSSED")
        self.assertEqual(len([c for c in self.store.records("setup_confirmations.jsonl") if c["setup_id"] == first["setup_id"]]), 1)

    def test_invalidated_at_the_stop_records_its_level_closure(self):
        first = self.store.scan(sr_obs("LONG", "DEVELOPING"))[0]
        self.store.scan(sr_obs(None, bar=1, price=2598.0))           # below the stop (2599)
        closing = self.store.events_for(first["setup_id"])[-1]
        self.assertEqual((closing["to_state"], closing["reason_code"]), ("INVALIDATED", "INVALIDATION_PRICE_CROSSED"))
        self.assertEqual(closing["metadata"][LEVEL_CLOSURE],
                         {"level": {"zone_low": SUPPORT[0], "zone_high": SUPPORT[1]}, "bar_time": T0 + 2 * BAR})


class SuppressionTests(EpisodeTestCase):
    def stopped_out(self):
        first = self.store.scan(sr_obs("LONG", "DEVELOPING", bar=0))[0]
        self.store.scan(sr_obs(None, bar=1, price=2598.0))           # stop crossed while bar T0+2 forms
        return first["setup_id"]

    def test_the_same_test_of_the_same_level_is_suppressed_without_duplicates(self):
        closed = self.stopped_out()
        before = self.sr_ids()
        for bar, bars_ago in ((2, 0), (3, 1)):
            # Same level, the touch is on the bar that closed the episode: no new test.
            again = self.store.scan(sr_obs("LONG", "DEVELOPING", bar=bar, bars_ago=bars_ago))[0]
            self.assertEqual((again["setup_id"], again["lifecycle_state"], again["episode_suppressed"]),
                             (closed, "INVALIDATED", True))
            watching = self.store.scan(sr_obs("LONG", "WATCHING", bar=bar))[0]
            self.assertTrue(watching["episode_suppressed"], "watching the failed level again is not a new setup")
        self.assertEqual(self.sr_ids(), before)

    def test_a_new_test_of_the_level_opens_exactly_one_new_episode(self):
        closed = self.stopped_out()
        fresh = [self.store.scan(sr_obs("LONG", "DEVELOPING", bar=bar, bars_ago=bar - 3))[0] for bar in (3, 4, 5)]
        self.assertFalse(any(r.get("episode_suppressed") for r in fresh))
        self.assertEqual(len({r["setup_id"] for r in fresh}), 1)
        self.assertNotEqual(fresh[0]["setup_id"], closed, "an old setup is never resurrected")
        self.assertEqual(fresh[0]["lifecycle_state"], "DEVELOPING")
        # The new episode continues while it waits near the level; the old closure never captures it.
        waiting = self.store.scan(sr_obs("LONG", "WATCHING", bar=6))[0]
        self.assertEqual((waiting["setup_id"], waiting.get("episode_suppressed")), (fresh[0]["setup_id"], None))

    def test_another_level_or_the_other_direction_is_never_suppressed(self):
        self.stopped_out()
        lower = self.store.scan(sr_obs("LONG", "WATCHING", zone=(2580.0, 2583.0), price=2585.0, bar=2))[0]
        short = self.store.scan(sr_obs("SHORT", "WATCHING", zone=(2596.0, 2599.0), price=2595.0, bar=2))[0]
        self.assertFalse(lower.get("episode_suppressed") or short.get("episode_suppressed"))

    def test_suppression_survives_a_restart(self):
        closed = self.stopped_out()
        forget_process_state(self.store.root)
        again = self.store.scan(sr_obs("LONG", "WATCHING", bar=2))[0]
        self.assertEqual((again["setup_id"], again.get("episode_suppressed")), (closed, True))
        forget_process_state(self.store.root)
        fresh = self.store.scan(sr_obs("LONG", "DEVELOPING", bar=4, bars_ago=0))[0]
        self.assertFalse(fresh.get("episode_suppressed"))

    def test_expiry_suppresses_nothing(self):
        first = self.store.scan(sr_obs("LONG", "WATCHING"))[0]
        self.store.scan(sr_obs(None, bar=1, price=2640.0))           # expired by displacement
        back = self.store.scan(sr_obs("LONG", "WATCHING", bar=2))[0]
        self.assertFalse(back.get("episode_suppressed"))
        self.assertNotEqual(back["setup_id"], first["setup_id"])


class HistoricalClosureTests(EpisodeTestCase):
    def test_historical_direction_flip_invalidations_no_longer_suppress_and_are_not_rewritten(self):
        # Write history exactly as the former policy did: the flip INVALIDATES and then suppresses.
        with mock.patch.object(observations, "_level_episodes_policy", lambda *args: False), \
                mock.patch.object(observations, "_confirmed_events_policy", lambda *args: False):
            old = self.store.scan(sr_obs("LONG", "WATCHING"))[0]
            self.store.scan(sr_obs("SHORT", "WATCHING", bar=1))
            poisoned = self.store.scan(sr_obs("LONG", "WATCHING", bar=2))[0]
        self.assertEqual(closures(self.store, old["setup_id"]), [("INVALIDATED", "DIRECTION_CHANGED")])
        self.assertTrue(poisoned["episode_suppressed"], "the former behaviour this fix removes")
        history = {name: (self.store.root / name).read_bytes() for name in
                   ("setup_observations.jsonl", "setup_lifecycle.jsonl")}
        forget_process_state(self.store.root)
        rounds = [self.store.scan(sr_obs("LONG", "WATCHING", bar=bar))[0] for bar in (3, 4, 5)]
        self.assertFalse(any(r.get("episode_suppressed") for r in rounds))
        self.assertEqual(len({r["setup_id"] for r in rounds}), 1, "one new episode, then continued")
        self.assertNotEqual(rounds[0]["setup_id"], old["setup_id"])
        for name, data in history.items():
            self.assertTrue((self.store.root / name).read_bytes().startswith(data), name + " history is append-only")


class IndependenceTests(EpisodeTestCase):
    def test_three_strategies_on_one_symbol_are_three_independent_episodes(self):
        rounds = [self.store.scan(market("SHORT", strategies.TRENDLINE, state="CONFIRMING", price=2620.0),
                                  sr_obs("SHORT", "DEVELOPING", bar=i),
                                  market("SHORT", "trend_momentum", state="WATCHING", price=2620.0, anchors=None))
                  for i in range(3)]
        for column in range(3):
            self.assertEqual(len({batch[column]["setup_id"] for batch in rounds}), 1)
        self.assertEqual(len({batch[column]["setup_id"] for batch in rounds for column in range(3)}), 3)
        self.assertFalse(any(row.get("episode_suppressed") for batch in rounds for row in batch))

    def test_a_closed_sr_level_never_suppresses_trendline_or_trend_momentum(self):
        self.store.scan(sr_obs("LONG", "DEVELOPING"))
        self.store.scan(sr_obs(None, bar=1, price=2598.0))
        tl, tm = self.store.scan(market("LONG", strategies.TRENDLINE, price=2602.0),
                                 market("LONG", "trend_momentum", price=2602.0, anchors=None))
        self.assertFalse(tl.get("episode_suppressed") or tm.get("episode_suppressed"))

    def test_closed_trendline_and_trend_momentum_episodes_never_suppress_sr(self):
        self.store.scan(market("LONG", strategies.TRENDLINE, price=2605.0, invalidation=2600.0),
                        market("LONG", "trend_momentum", price=2605.0, invalidation=2600.0, anchors=None))
        self.store.scan(market("LONG", strategies.TRENDLINE, price=2590.0, invalidation=2600.0),
                        market("LONG", "trend_momentum", price=2590.0, invalidation=2600.0, anchors=None))
        opened = self.store.scan(sr_obs("LONG", "DEVELOPING", bar=2))[0]
        self.assertFalse(opened.get("episode_suppressed"))


class FullPathCompetingHypothesisTests(CompetingHypothesisTests):
    full_path = True


class FullPathSuppressionTests(SuppressionTests):
    full_path = True


class FullPathHistoricalClosureTests(HistoricalClosureTests):
    full_path = True


if __name__ == "__main__":
    unittest.main()
