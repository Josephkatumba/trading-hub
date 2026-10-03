"""The v5 replacement: trendline-first-v5 (strategy_id "trendline_v5") is the live trendline.

A  production lineup: exactly one trendline (v5), S/R and Trend / Momentum; the retired
   v4 ("trendline") is not registered and cannot produce records through the scan loop;
B  the real scan loop stamps trendline_v5 on the top-level market and its records; one
   trendline setup per market, never a duplicate;
C  historical v4 records stay exactly as written (never relabelled); v4 closed episodes
   never suppress, continue or absorb a v5 episode, even on the same trendline;
D  performance keeps the old and new trendline apart;
E  production wiring gives the live trendline the confirmed-events lifecycle.
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

import observations  # noqa: E402
import strategies  # noqa: E402
from episode_identity import CONFIRMED_EVENTS_LIFECYCLE  # noqa: E402
from performance import performance_report  # noqa: E402
from strategies import REGISTRY, TRENDLINE, TrendlineStrategy, TrendlineV5Strategy  # noqa: E402
from test_strategy_isolation import IsolationTestCase, market  # noqa: E402
from test_strategy_registry import FakeMT5  # noqa: E402

LIVE_IDS = ["trendline_v5", "support_resistance", "trend_momentum", "smc"]


def production_scan(root: Path):
    """main.market_snapshot with the PRODUCTION registry (nothing patched but MT5, clock and store)."""
    import main
    fixtures = [{**f, "symbol": s} for f, s in zip([f for f in g.load_fixtures() if f["name"] in ("real_XAUUSD", "real_EURUSD")],
                                                   ("XAUUSD", "EURUSD"))]
    main._MT5_SESSION.update(initialized=False, initializations=0)
    try:
        with g.isolated_store(observations, root), \
             mock.patch.object(main, "mt5", FakeMT5(fixtures)), \
             mock.patch.object(main, "mt5_symbol", side_effect=lambda s: s if s in ("XAUUSD", "EURUSD") else None), \
             mock.patch.object(main, "datetime", g.FrozenClock.make()), \
             mock.patch.object(main, "resolve_due_market_outcomes", return_value=[]):
            markets = main.market_snapshot()
    finally:
        main._MT5_SESSION.update(initialized=False, initializations=0)
    return markets


class ProductionLineupTests(unittest.TestCase):
    def test_a_exactly_one_live_trendline_and_it_is_v5(self):
        self.assertEqual(REGISTRY.registered(), LIVE_IDS)
        self.assertEqual(REGISTRY.live(), LIVE_IDS)
        self.assertEqual((TRENDLINE, REGISTRY.get(TRENDLINE).version), ("trendline_v5", "trendline-first-v5.1"))
        self.assertIsInstance(REGISTRY.get(TRENDLINE), TrendlineV5Strategy)
        self.assertEqual([sid for sid in REGISTRY.registered() if "trendline" in sid], ["trendline_v5"], "no duplicate trendline")
        with self.assertRaises(KeyError):
            REGISTRY.get("trendline")                  # the retired v4 id is not registered
        self.assertEqual((TrendlineStrategy.strategy_id, TrendlineStrategy.version), ("trendline", "trendline-first-v4"))

    def test_b_the_scan_loop_runs_v5_and_stamps_its_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markets = production_scan(root)
            snapshots = [json.loads(line) for line in (root / "setup_observations.jsonl").read_text().splitlines()]
        self.assertTrue(markets)
        for row in markets:
            self.assertEqual((row["strategy_id"], row["strategy_version"]), ("trendline_v5", "trendline-first-v5.1"))
            self.assertEqual([entry["strategy_id"] for entry in row["strategies"]], LIVE_IDS)
            trend = [entry for entry in row["strategies"] if "trendline" in entry["strategy_id"]]
            self.assertEqual(len(trend), 1, "one trendline result per market")
        self.assertNotIn("trendline", {s["strategy_id"] for s in snapshots}, "the retired v4 writes nothing")
        v5 = [s for s in snapshots if s["strategy_id"] == "trendline_v5"]
        self.assertTrue(v5)
        self.assertEqual({s["strategy_version"] for s in v5}, {"trendline-first-v5.1"})
        per_symbol = {}
        for s in v5:
            per_symbol.setdefault(s["symbol"], set()).add(s["setup_id"])
        self.assertTrue(all(len(ids) == 1 for ids in per_symbol.values()), "one trendline episode per market per scan")


class HistoryIsolationTests(IsolationTestCase):
    def test_c_v4_history_is_untouched_and_never_absorbs_or_suppresses_v5(self):
        with g.v4_lineup(observations):
            v4_long = self.store.scan(market("LONG", invalidation=2600.0))[0]          # a v4 episode (strategy_id "trendline")
            self.store.scan(market("SHORT", invalidation=2700.0))                        # ... closed by a direction change
        before = {name: (self.store.root / name).read_bytes() for name in g.PERSISTED_FILES if (self.store.root / name).exists()}
        # The live v5 observes the same market, direction and trendline anchors.
        v5 = self.store.scan(market("LONG", TRENDLINE, invalidation=2600.0))[0]
        self.assertNotEqual(v5["setup_id"], v4_long["setup_id"])
        self.assertNotIn("episode_suppressed", v5, "a closed v4 episode never suppresses the new trendline")
        for name, data in before.items():
            self.assertTrue((self.store.root / name).read_bytes().startswith(data), name + " is append-only")
        snapshots = self.store.records("setup_observations.jsonl")
        self.assertEqual({(s["strategy_id"], s["strategy_version"]) for s in snapshots if s["setup_id"] == v4_long["setup_id"]},
                         {("trendline", "trendline-first-v4")}, "v4 records are never relabelled")
        self.assertEqual({(s["strategy_id"], s["strategy_version"]) for s in snapshots if s["setup_id"] == v5["setup_id"]},
                         {("trendline_v5", "trendline-first-v5.1")})
        self.assertEqual([e["to_state"] for e in self.store.events_for(v4_long["setup_id"])], ["DEVELOPING", "INVALIDATED"])

    def test_c_an_open_v4_episode_is_never_continued_by_v5(self):
        with g.v4_lineup(observations):
            v4 = self.store.scan(market("LONG", invalidation=2600.0))[0]
        v5 = self.store.scan(market("LONG", TRENDLINE, invalidation=2600.0))[0]
        self.assertNotEqual(v5["setup_id"], v4["setup_id"])
        self.assertEqual([e["to_state"] for e in self.store.events_for(v4["setup_id"])], ["DEVELOPING"])

    def test_d_performance_keeps_the_old_and_new_trendline_apart(self):
        with g.v4_lineup(observations):
            self.store.scan(market("LONG", state="CONFIRMING", valid=True, invalidation=2600.0, symbol="EURUSD"))
        self.store.scan(market("LONG", TRENDLINE, state="CONFIRMING", valid=True, invalidation=2600.0))
        confirmations = self.store.records("setup_confirmations.jsonl")
        self.assertEqual(sorted((c["strategy_id"], c["strategy_version"]) for c in confirmations),
                         [("trendline", "trendline-first-v4"), ("trendline_v5", "trendline-first-v5.1")])
        report = performance_report(confirmations, [], self.store.records("setup_observations.jsonl"),
                                    report_date=g.BASE_NOW.date().isoformat(), timezone_name="UTC")
        by_strategy = report["daily"][0]["by_strategy"]
        # One confirmation each, counted in separate groups: never combined into one "trendline" figure.
        self.assertEqual(by_strategy["trendline"]["pending"], 1)
        self.assertEqual(by_strategy["trendline_v5"]["pending"], 1)


class ProductionLifecycleTests(IsolationTestCase):
    def test_e_the_live_trendline_uses_the_confirmed_events_lifecycle_in_production(self):
        self.assertEqual(REGISTRY.get(TRENDLINE).lifecycle, CONFIRMED_EVENTS_LIFECYCLE)
        self.assertIs(observations.STRATEGIES, REGISTRY, "no patched registry: the production wiring")
        sid = self.store.scan(market("LONG", TRENDLINE, invalidation=2640.0))[0]["setup_id"]
        self.store.scan(market("LONG", TRENDLINE, state="CONFIRMING", valid=True, invalidation=2640.0))
        self.store.scan(market("SHORT", TRENDLINE, context=True))                     # a later bearish candle
        self.assertEqual([e["to_state"] for e in self.store.events_for(sid)], ["DEVELOPING", "CONFIRMED"])
        self.store.scan(market("SHORT", TRENDLINE, context=True, price=2680.5))        # through the confirmed target
        event = self.store.events_for(sid)[-1]
        self.assertEqual((event["to_state"], event["reason_code"]), ("RESOLVED", "TARGET_PRICE_CROSSED"))
        self.assertEqual(len([c for c in self.store.records("setup_confirmations.jsonl") if c["setup_id"] == sid]), 1,
                         "the confirmation is a single historical event")

    def test_e_before_confirmation_the_live_trendline_is_still_invalidated(self):
        sid = self.store.scan(market("LONG", TRENDLINE, invalidation=2640.0))[0]["setup_id"]
        self.store.scan(market("SHORT", TRENDLINE, invalidation=2660.0))
        self.assertEqual(self.store.events_for(sid)[-1]["reason_code"], "DIRECTION_CHANGED")


if __name__ == "__main__":
    unittest.main()
