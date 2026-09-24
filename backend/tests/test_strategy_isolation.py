"""Strategy isolation: scaffolding for the multi-strategy work (Phase 0).

Mandated rule: a setup from one strategy must never invalidate, suppress, modify
or cancel a setup from another strategy; state is isolated by strategy_id, and
opposing strategies coexist (a conflict is information, not a decision).

Today episodes are scoped by symbol + timeframe only, so these rules do NOT
hold yet. The target tests are marked expectedFailure and document the gap.
Phase 3 (strategy_id scoping) must make them pass; an unexpected success then
fails the suite, forcing the marker to be removed.

The baseline tests must keep passing throughout: within ONE strategy a
direction change still invalidates the episode, and context episodes (market
observations) never become confirmed setups.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g  # noqa: E402
import observations  # noqa: E402

PHASE3 = "Phase 3: episodes and suppression are not scoped by strategy_id yet"


def market(direction="LONG", strategy_id=None, *, symbol="XAUUSD", state="DEVELOPING", valid=False,
           price=2650.0, invalidation=None, anchors=("08:00", "09:00"), family="BREAK", context=False):
    row = {"symbol": symbol, "timeframe": "M15", "direction": direction, "state": state, "price": price,
           "atr": 5.0, "score": 70, "score_breakdown": {"trendline": 20}, "strategy_valid": valid,
           "trendline_gate": not context, "confirmation_alignment": valid, "rr": 2.0 if valid else None,
           "setup_family": None if context else family, "trendline_state": "WATCHING" if context else family,
           "setup": "Directional context only" if context else "Trendline " + family.lower(),
           "invalidation_hint": invalidation, "entry": price,
           "stop_loss": None if context else invalidation, "take_profit": None if context else (price + 30 if direction == "LONG" else price - 30)}
    if anchors and not context:
        orientation = "ASCENDING_SUPPORT" if direction == "SHORT" else "DESCENDING_RESISTANCE"
        row["trendline_identity"] = {"orientation": orientation, "anchors": [
            {"time": "2026-09-24T" + anchors[0] + ":00Z", "price": price - 10}, {"time": "2026-09-24T" + anchors[1] + ":00Z", "price": price - 5}]}
    if strategy_id:
        row["strategy_id"] = strategy_id
    return row


class Store:
    """Runs scan rounds through observations.record_markets on a temp store."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.context = g.isolated_store(observations, self.root)
        self.context.__enter__()
        self.round = 0

    def scan(self, *markets):
        g.FrozenClock.current = g.BASE_NOW + timedelta(minutes=15 * self.round)
        self.round += 1
        batch = [dict(m) for m in markets]
        observations.record_markets(batch)
        return batch

    def records(self, name):
        path = self.root / name
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def events_for(self, setup_id):
        return [e for e in self.records("setup_lifecycle.jsonl") if e["setup_id"] == setup_id]

    def close(self):
        self.context.__exit__(None, None, None)
        self.tmp.cleanup()


class IsolationTestCase(unittest.TestCase):
    def setUp(self):
        self.store = Store()

    def tearDown(self):
        self.store.close()


class BaselineBehaviourTests(IsolationTestCase):
    """Current behaviour that the multi-strategy work must preserve."""

    def test_same_strategy_direction_change_still_invalidates(self):
        first = self.store.scan(market("LONG"))[0]
        second = self.store.scan(market("SHORT"))[0]
        self.assertNotEqual(first["setup_id"], second["setup_id"])
        closing = [e for e in self.store.events_for(first["setup_id"]) if e["to_state"] == "INVALIDATED"]
        self.assertEqual([e["reason_code"] for e in closing], ["DIRECTION_CHANGED"])

    def test_context_episode_is_an_observation_never_a_confirmed_setup(self):
        observed = self.store.scan(market("LONG", context=True, state="WATCHING"))[0]
        self.store.scan(market("LONG", context=True, state="WATCHING"))
        snapshots = self.store.records("setup_observations.jsonl")
        self.assertTrue(snapshots)
        self.assertEqual({s["setup_type"] for s in snapshots}, {"WATCHING"})
        self.assertEqual(self.store.records("setup_confirmations.jsonl"), [])
        self.assertTrue(all(s["proposed_stop_loss"] is None and s["proposed_take_profit"] is None for s in snapshots))
        self.assertNotIn(observed["lifecycle_state"], {"CONFIRMED", "ACTIVE"})

    def test_confirmed_trendline_setup_produces_exactly_one_confirmation(self):
        confirmed = market("LONG", state="CONFIRMING", valid=True, invalidation=2600.0)
        first = self.store.scan(confirmed)[0]
        self.store.scan(confirmed)
        confirmations = self.store.records("setup_confirmations.jsonl")
        self.assertEqual([c["setup_id"] for c in confirmations], [first["setup_id"]])


class StrategyIsolationTargetTests(IsolationTestCase):
    """Mandated isolation rules. Expected to fail until Phase 3."""

    @unittest.expectedFailure
    def test_opposing_strategy_does_not_invalidate_a_trendline_setup(self):
        trendline = self.store.scan(market("LONG", "trendline_break"))[0]
        self.store.scan(market("SHORT", "smc", anchors=None, family="REVERSAL"))
        closing = [e for e in self.store.events_for(trendline["setup_id"]) if e["to_state"] in {"INVALIDATED", "EXPIRED"}]
        self.assertEqual(closing, [], PHASE3)

    @unittest.expectedFailure
    def test_opposing_strategies_coexist_as_separate_tagged_setups(self):
        for _ in range(2):
            trendline, smc = self.store.scan(market("LONG", "trendline_break"), market("SHORT", "smc", anchors=None, family="REVERSAL"))
        self.assertNotEqual(trendline["setup_id"], smc["setup_id"])
        snapshots = self.store.records("setup_observations.jsonl")
        tagged = {s["setup_id"]: s.get("strategy_id") for s in snapshots}
        self.assertEqual(tagged.get(trendline["setup_id"]), "trendline_break", PHASE3)
        self.assertEqual(tagged.get(smc["setup_id"]), "smc", PHASE3)
        for setup_id in (trendline["setup_id"], smc["setup_id"]):
            self.assertFalse([e for e in self.store.events_for(setup_id) if e["to_state"] in {"INVALIDATED", "EXPIRED"}], PHASE3)

    @unittest.expectedFailure
    def test_closed_setup_of_one_strategy_does_not_suppress_another(self):
        # An S/R episode (no trendline geometry) is invalidated by price...
        self.store.scan(market("LONG", "support_resistance", anchors=None, invalidation=2640.0))
        self.store.scan(market("LONG", "support_resistance", anchors=None, invalidation=2640.0, price=2635.0))
        # ...then a trendline setup appears nearby in the same direction: it must open, not be suppressed.
        trendline = self.store.scan(market("LONG", "trendline_break", anchors=None, price=2636.0))[0]
        self.assertFalse(trendline.get("episode_suppressed"), PHASE3)

    @unittest.expectedFailure
    def test_confirmation_of_one_strategy_leaves_another_untouched(self):
        trendline = self.store.scan(market("LONG", "trendline_break"))[0]
        before = self.store.events_for(trendline["setup_id"])
        self.store.scan(market("SHORT", "smc", anchors=None, family="REVERSAL", state="CONFIRMING", valid=True, invalidation=2700.0))
        self.assertEqual(self.store.events_for(trendline["setup_id"]), before, PHASE3)
        confirmations = self.store.records("setup_confirmations.jsonl")
        self.assertEqual([c.get("strategy_id") for c in confirmations], ["smc"], PHASE3)


if __name__ == "__main__":
    unittest.main()
