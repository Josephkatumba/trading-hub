"""trendline-first-v5 in SHADOW mode (strategy_id trendline-first-v5-shadow) beside the live v4.

A  the real scan loop (main.market_snapshot on a fake MT5) runs v5 shadow alongside
   v4 / S/R / Trend-Momentum; the live strategies' markets and records are byte-identical
   with and without it; its records carry its own strategy_id and the shadow flag;
B  it is v5: closed bars only, H1 structural targets, confirmed-events lifecycle;
C  after confirmation only its stop or target closes it; it never touches v4 episodes;
D  it cannot trade, alert or appear live; the experiment report and health diagnostics;
E  the kill switch removes it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
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
from shadow_report import shadow_report  # noqa: E402
from strategies import (LIVE, SHADOW, StrategyRegistry, SupportResistanceStrategy, TrendMomentumStrategy,  # noqa: E402
                        TrendlineStrategy, TRENDLINE_V5_SHADOW, TrendlineV5ShadowStrategy, build_default_registry)
from strategies.base import MarketInput  # noqa: E402
from strategies.trendline import TrendlineV5Strategy  # noqa: E402
from test_strategy_isolation import IsolationTestCase, market  # noqa: E402
from test_strategy_registry import FakeMT5  # noqa: E402
from v5_fixtures import BASIS, forming_variants, h1_rows, m15_rows  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
STOP, PRICE = 2640.0, 2650.0


def experiment_registry() -> StrategyRegistry:
    """The lineup that ran during the shadow experiment: v4 LIVE (as "trendline"), S/R and
    T/M LIVE, and trendline-first-v5-shadow in SHADOW. The experiment ended when v5 replaced
    v4 as the live trendline; these tests keep its architecture and records verifiable."""
    registry = live_registry()
    registry.register(TrendlineV5ShadowStrategy(), enabled=True, mode=SHADOW)
    return registry


def live_registry() -> StrategyRegistry:
    """Production before the replacement, without the experiment: v4, S/R, Trend-Momentum (LIVE)."""
    registry = StrategyRegistry()
    registry.register(TrendlineStrategy(), enabled=True, mode=LIVE)
    registry.register(SupportResistanceStrategy(), enabled=True, mode=LIVE)
    registry.register(TrendMomentumStrategy(), enabled=True, mode=LIVE)
    return registry


def shadow(direction="LONG", **kwargs):
    return market(direction, TRENDLINE_V5_SHADOW, **kwargs)


def real_scan(registry: StrategyRegistry, root: Path):
    import main
    fixtures = [{**f, "symbol": s} for f, s in zip([f for f in g.load_fixtures() if f["name"] in ("real_XAUUSD", "real_EURUSD")],
                                                   ("XAUUSD", "EURUSD"))]
    main._MT5_SESSION.update(initialized=False, initializations=0)
    try:
        with g.isolated_store(observations, root), \
             mock.patch.object(observations, "STRATEGIES", registry), \
             mock.patch.object(main, "mt5", FakeMT5(fixtures)), \
             mock.patch.object(main, "STRATEGIES", registry), \
             mock.patch.object(main, "TRENDLINE", "trendline"), \
             mock.patch.object(main, "mt5_symbol", side_effect=lambda s: s if s in ("XAUUSD", "EURUSD") else None), \
             mock.patch.object(main, "datetime", g.FrozenClock.make()), \
             mock.patch.object(main, "resolve_due_market_outcomes", return_value=[]):
            markets = main.market_snapshot()
            scan = dict(main._LAST_SCAN)
    finally:
        main._MT5_SESSION.update(initialized=False, initializations=0)
    files = {name: (root / name).read_bytes() for name in g.PERSISTED_FILES if (root / name).exists()}
    return markets, files, scan


ID = re.compile(rb"(stp|obs|evt|cnf|conf)_[0-9a-f]{12,32}")


def normalise_ids(value):
    """Replace uuid-derived record ids (the temp store's counter) with a placeholder."""
    if isinstance(value, bytes):
        return ID.sub(lambda match: match.group(1) + b"_ID", value)
    return json.loads(normalise_ids(json.dumps(value, sort_keys=True).encode()))


def lines(blob: bytes | None):
    return [json.loads(line) for line in (blob or b"").splitlines()]


class ScanLoopTests(unittest.TestCase):
    """A: the real scan loop, with and without the shadow strategy."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.live = real_scan(live_registry(), Path(cls.tmp.name) / "live")
        cls.both = real_scan(experiment_registry(), Path(cls.tmp.name) / "both")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_1_v5_shadow_runs_alongside_the_live_strategies(self):
        markets, _, scan = self.both
        self.assertTrue(markets)
        for row in markets:
            entries = {entry["strategy_id"]: entry for entry in row["strategies"]}
            self.assertEqual(list(entries), ["trendline", "support_resistance", "trend_momentum", TRENDLINE_V5_SHADOW])
            self.assertEqual((entries[TRENDLINE_V5_SHADOW]["mode"], entries[TRENDLINE_V5_SHADOW]["status"]), (SHADOW, "OK"))
            self.assertEqual(entries[TRENDLINE_V5_SHADOW]["strategy_version"], "trendline-first-v5")
            self.assertEqual((entries["trendline"]["mode"], entries["trendline"]["strategy_version"]), (LIVE, "trendline-first-v4"))
        self.assertEqual(scan["strategy_results"][TRENDLINE_V5_SHADOW], {"ok": len(markets), "error": 0})

    def test_2_and_14_records_are_independent_and_keep_the_shadow_strategy_id(self):
        _, files, _ = self.both
        snapshots = lines(files.get("setup_observations.jsonl"))
        mine = [s for s in snapshots if s["strategy_id"] == TRENDLINE_V5_SHADOW]
        others = [s for s in snapshots if s["strategy_id"] != TRENDLINE_V5_SHADOW]
        self.assertTrue(mine, "the fixtures produce shadow observations")
        self.assertTrue(all(s["shadow"] is True and s["strategy_version"] == "trendline-first-v5" for s in mine))
        self.assertTrue(all("shadow" not in s for s in others))
        self.assertFalse({s["setup_id"] for s in mine} & {s["setup_id"] for s in others})
        for field in ("symbol", "direction", "setup_type", "lifecycle_state", "proposed_entry", "proposed_stop_loss", "proposed_take_profit"):
            self.assertIn(field, mine[0])

    def test_3_4_5_live_strategies_are_unchanged_by_the_shadow_strategy(self):
        live_markets, live_files, _ = self.live
        markets, files, _ = self.both
        strip = lambda rows: [{k: v for k, v in m.items() if k != "strategies"} for m in rows]  # noqa: E731
        self.assertEqual(g.canonical(strip(markets)), g.canonical(strip(live_markets)))       # v4 market payload
        # The temp store numbers ids with one counter across all records, so the extra shadow
        # records shift the synthetic ids of S/R and T/M records written after them. Decisions
        # and records are compared with those ids normalised; v4 (written first) byte for byte.
        for before, after in zip(live_markets, markets):
            self.assertEqual(normalise_ids(before["strategies"]), normalise_ids(after["strategies"][:3]))
        by_strategy = lambda blob, sid: [l for l in blob.splitlines(keepends=True) if json.loads(l)["strategy_id"] == sid]  # noqa: E731
        live_obs, obs = live_files["setup_observations.jsonl"], files["setup_observations.jsonl"]
        self.assertEqual(b"".join(by_strategy(obs, "trendline")), b"".join(by_strategy(live_obs, "trendline")))   # v4 byte-identical
        for strategy_id in ("support_resistance", "trend_momentum"):
            with self.subTest(strategy=strategy_id):
                self.assertEqual(normalise_ids(b"".join(by_strategy(obs, strategy_id))), normalise_ids(b"".join(by_strategy(live_obs, strategy_id))))
        v4_ids = {json.loads(l)["setup_id"] for l in by_strategy(obs, "trendline")}
        events = [l for l in files["setup_lifecycle.jsonl"].splitlines(keepends=True) if json.loads(l)["setup_id"] in v4_ids]
        live_events = [l for l in live_files["setup_lifecycle.jsonl"].splitlines(keepends=True) if json.loads(l)["setup_id"] in v4_ids]
        self.assertEqual(b"".join(events), b"".join(live_events))


class V5BehaviourTests(unittest.TestCase):
    """B: the shadow strategy is v5, unchanged."""

    def evaluate(self, strategy, seed, forming="flat"):
        full = m15_rows(seed)
        closed = full[:-1]
        bar = forming_variants(closed[-1], 0.2)[forming]
        return strategy.evaluate(MarketInput("XAUUSD", closed + [bar], higher_rows=h1_rows(full)))

    def test_it_is_v5_with_its_own_identity(self):
        self.assertEqual((TrendlineV5ShadowStrategy.strategy_id, TrendlineV5ShadowStrategy.version), (TRENDLINE_V5_SHADOW, "trendline-first-v5"))
        self.assertEqual(TrendlineV5ShadowStrategy.lifecycle, CONFIRMED_EVENTS_LIFECYCLE)
        for seed in range(20):
            self.assertEqual(self.evaluate(TrendlineV5ShadowStrategy(basis=BASIS), seed), self.evaluate(TrendlineV5Strategy(basis=BASIS), seed))

    def test_6_closed_candles_only(self):
        for seed in range(20):
            results = {name: self.evaluate(TrendlineV5ShadowStrategy(basis=BASIS), seed, name) for name in ("flat", "surge_up", "crash_down", "wick_up_reject")}
            self.assertEqual(len({json.dumps(r, sort_keys=True, default=str) for r in results.values()}), 1)

    def test_7_h1_structural_targets(self):
        result = self.evaluate(TrendlineV5ShadowStrategy(basis=BASIS), 31)
        self.assertEqual(result["target_basis"], "H1_SWING")
        self.assertTrue(result["strategy_valid"])
        self.assertGreaterEqual(result["rr"], 1.5)


class ShadowLifecycleTests(IsolationTestCase):
    """C: the confirmed-events lifecycle under the shadow strategy_id (production registry)."""

    def setUp(self):
        super().setUp()
        self.registry = mock.patch.object(observations, "STRATEGIES", experiment_registry())
        self.registry.start()

    def tearDown(self):
        self.registry.stop()
        super().tearDown()

    def confirm(self, direction="LONG"):
        stop = STOP if direction == "LONG" else PRICE + 10
        sid = self.store.scan(shadow(direction, invalidation=stop))[0]["setup_id"]
        self.store.scan(shadow(direction, state="CONFIRMING", valid=True, invalidation=stop))
        self.assertEqual([e["to_state"] for e in self.store.events_for(sid)], ["DEVELOPING", "CONFIRMED"])
        return sid

    def test_8_9_a_direction_change_after_confirmation_does_not_close_it(self):
        sid = self.confirm("LONG")
        self.store.scan(shadow("SHORT", context=True))
        self.store.scan(shadow("SHORT", invalidation=PRICE + 10))
        self.assertEqual([e["to_state"] for e in self.store.events_for(sid)], ["DEVELOPING", "CONFIRMED"])

    def test_pre_confirmation_invalidation_still_applies(self):
        sid = self.store.scan(shadow("LONG", invalidation=STOP))[0]["setup_id"]
        self.store.scan(shadow("SHORT", invalidation=PRICE + 10))
        self.assertEqual(self.store.events_for(sid)[-1]["reason_code"], "DIRECTION_CHANGED")

    def test_10_target_closes_it(self):
        sid = self.confirm("LONG")
        self.store.scan(shadow("SHORT", context=True, price=PRICE + 30.5))
        event = self.store.events_for(sid)[-1]
        self.assertEqual((event["to_state"], event["reason_code"]), ("RESOLVED", "TARGET_PRICE_CROSSED"))

    def test_11_stop_closes_it(self):
        sid = self.confirm("SHORT")
        self.store.scan(shadow("LONG", context=True, price=PRICE + 10.5))
        event = self.store.events_for(sid)[-1]
        self.assertEqual((event["to_state"], event["reason_code"]), ("INVALIDATED", "INVALIDATION_PRICE_CROSSED"))

    def test_13_shadow_records_never_touch_v4_episodes(self):
        v4 = self.store.scan(market("LONG", invalidation=STOP))[0]
        before = self.store.records("setup_observations.jsonl")
        mirror = self.store.scan(shadow("SHORT", invalidation=PRICE + 10), shadow("LONG", state="CONFIRMING", valid=True, invalidation=STOP, symbol="EURUSD"))
        self.assertNotIn(v4["setup_id"], {row["setup_id"] for row in mirror})
        self.assertEqual([e["to_state"] for e in self.store.events_for(v4["setup_id"])], ["DEVELOPING"])
        self.assertEqual(self.store.records("setup_observations.jsonl")[:len(before)], before)  # append-only
        confirmations = self.store.records("setup_confirmations.jsonl")
        self.assertEqual([(c["strategy_id"], c["shadow"]) for c in confirmations], [(TRENDLINE_V5_SHADOW, True)])


class NoTradingNoAlertsTests(IsolationTestCase):
    """D: observational only."""

    def test_12_no_execution_path_exists_in_the_engine(self):
        pattern = re.compile(r"order_send|order_check|TRADE_ACTION_|positions_open|place_order")
        offenders = [str(path.relative_to(BACKEND)) for path in BACKEND.glob("*.py") if pattern.search(path.read_text(encoding="utf-8"))]
        offenders += [str(path.relative_to(BACKEND)) for path in (BACKEND / "strategies").glob("*.py") if pattern.search(path.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [])

    def test_12_shadow_confirmations_are_never_live_alerts_or_live_episodes(self):
        with mock.patch.object(observations, "STRATEGIES", experiment_registry()):
            sid = self.store.scan(shadow("LONG", state="CONFIRMING", valid=True, invalidation=STOP))[0]["setup_id"]
            with g.isolated_store(observations, self.store.root):
                self.assertNotIn(sid, [row["setup_id"] for row in observations.setup_episodes("all", 100)])
                self.assertIn(sid, [row["setup_id"] for row in observations.setup_episodes("all", 100, include_shadow=True)])
        confirmations = self.store.records("setup_confirmations.jsonl")
        day = confirmations[0]["confirmed_at"][:10]
        report = performance_report(confirmations, [], self.store.records("setup_observations.jsonl"), day, timezone_name="UTC")
        daily = report["daily"][0] if report.get("daily") else report["summary"]
        self.assertEqual(daily.get("setups", []), [], "the setups list drives alerts: shadow never enters it")
        self.assertIn(TRENDLINE_V5_SHADOW, daily.get("shadow_strategies", []))

    def test_health_reports_the_shadow_state_without_changing_existing_fields(self):
        import main
        self.assertEqual(main.shadow_state(TRENDLINE_V5_SHADOW, {}), "WAITING_FOR_SCAN")
        self.assertEqual(main.shadow_state(TRENDLINE_V5_SHADOW, {"strategy_results": {TRENDLINE_V5_SHADOW: {"ok": 16, "error": 0}}}), "RUNNING")
        self.assertEqual(main.shadow_state(TRENDLINE_V5_SHADOW, {"strategy_results": {TRENDLINE_V5_SHADOW: {"ok": 0, "error": 16}}}), "ERROR")
        with mock.patch.object(main, "mt5", None):
            health = main.health()
        self.assertIs(health["execution_enabled"], False)
        # The experiment ended: v5 is the live trendline, nothing runs in SHADOW mode.
        self.assertEqual((health["strategy"], health["strategy_id"]), ("trendline-first-v5", "trendline_v5"))
        self.assertEqual((health["trendline_v5_shadow"], health["shadow_strategies"]), ("NOT_REGISTERED", []))
        with mock.patch.object(main, "mt5", None), mock.patch.object(main, "STRATEGIES", experiment_registry()), \
             mock.patch.object(main, "TRENDLINE", "trendline"):
            during = main.health()
        self.assertIn(during["trendline_v5_shadow"], {"RUNNING", "WAITING_FOR_SCAN", "PARTIAL_ERRORS", "ERROR"})
        self.assertEqual([item["strategy_id"] for item in during["shadow_strategies"]], [TRENDLINE_V5_SHADOW])

    def test_experiment_report_counts_only_real_outcomes(self):
        with mock.patch.object(observations, "STRATEGIES", experiment_registry()):
            long = self.store.scan(shadow("LONG", invalidation=STOP))[0]["setup_id"]
            self.store.scan(shadow("LONG", state="CONFIRMING", valid=True, invalidation=STOP))
            self.store.scan(shadow("SHORT", context=True))                                      # no effect after confirmation
            self.store.scan(shadow("SHORT", context=True, price=PRICE + 30.5))                   # target
            eur = self.store.scan(shadow("SHORT", invalidation=PRICE + 10, symbol="EURUSD"))[0]["setup_id"]
            self.store.scan(shadow("SHORT", state="CONFIRMING", valid=True, invalidation=PRICE + 10, symbol="EURUSD"))
            self.store.scan(shadow("LONG", context=True, price=PRICE + 10.5, symbol="EURUSD"))    # stop
            self.store.scan(shadow("LONG", invalidation=STOP, symbol="GBPUSD"))
            self.store.scan(shadow("SHORT", invalidation=PRICE + 10, symbol="GBPUSD"))             # pre-confirmation invalidation
            with g.isolated_store(observations, self.store.root):
                episodes = observations.setup_episodes("all", 1000, include_shadow=True)
        report = shadow_report(TRENDLINE_V5_SHADOW, episodes + [dict(e, strategy_id="trendline") for e in episodes],
                               self.store.records("setup_lifecycle.jsonl"), self.store.records("setup_confirmations.jsonl"), [])
        self.assertEqual(report["confirmed"], 2)
        self.assertEqual((report["outcomes"]["target_hit"], report["outcomes"]["stop_hit"], report["outcomes"]["still_open"]), (1, 1, 0))
        self.assertEqual(report["rates"]["target_hit_rate"], {"value": 50.0, "numerator": 1, "denominator": 2})
        self.assertEqual(report["direction_change_closures_after_confirmation"], 0)
        self.assertGreaterEqual(report["direction_change_invalidations_before_confirmation"], 1)
        self.assertEqual(sorted(report["nominal_r"]["values"]), [-1.0, 2.0])
        self.assertEqual(set(report["by_symbol"]), {"XAUUSD", "EURUSD"})
        self.assertEqual({row["setup_id"] for row in report["confirmed_setups"]}, {long, eur})


class ExperimentEndedTests(unittest.TestCase):
    def test_v5_is_live_and_the_shadow_copy_is_no_longer_registered(self):
        registry = build_default_registry()
        self.assertNotIn(TRENDLINE_V5_SHADOW, registry.registered(), "no duplicate v5 evaluation")
        self.assertEqual(registry.live(), ["trendline_v5", "support_resistance", "trend_momentum"])
        self.assertEqual(registry.get("trendline_v5").version, TrendlineV5ShadowStrategy.version)
        # Same decisions under both identities: the shadow records measured what now runs live.
        self.assertEqual(TrendlineV5ShadowStrategy.evaluate, strategies.TrendlineV5Strategy.evaluate)
        self.assertEqual(TrendlineV5ShadowStrategy.lifecycle, strategies.TrendlineV5Strategy.lifecycle)


if __name__ == "__main__":
    unittest.main()
