"""Phase 2: strategy contract + registry, with the trendline engine as the only strategy.

Adapter equivalence: TrendlineStrategy output == scanner.analyze_symbol output
(labelled with the strategy's version: trendline-first-v4 since the Phase 9 session
correction; LegacyTrendlineStrategy reproduces the v3 output exactly), and its
record == that output + exactly the approved metadata (strategy_id).
Registry isolation: trendline runs through the registry; disabled strategies
produce nothing; registering, enabling, failing or input-mutating future
strategies cannot change the trendline result. The scan loop in main keeps
building the market dict from the unmodified trendline payload.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g  # noqa: E402

import scanner  # noqa: E402
import strategies  # noqa: E402
from strategies import (CORE_FIELDS, METADATA_FIELDS, LegacyTrendlineStrategy, MarketInput, Strategy,  # noqa: E402
                        StrategyRegistry, TrendlineStrategy, build_default_registry)
from test_trendline_invariants import results as random_scans, walk  # noqa: E402


def market_input(fixture: dict) -> MarketInput:
    return MarketInput(fixture["symbol"], fixture["rows"], spread=fixture.get("spread", 0.0),
                       session_context=fixture.get("session_context"), higher_rows=fixture.get("higher_rows"))


class FutureStrategy(Strategy):
    """A stand-in for a later strategy; its rules are irrelevant here."""
    strategy_id = "future"
    version = "future-v0"
    timeframe = "M15"
    lifecycle = "future-lifecycle"

    def evaluate(self, market):
        return {"state": "WATCHING", "direction": "SHORT", "strategy_valid": False, "score": 1, "score_breakdown": {}}


class FailingStrategy(FutureStrategy):
    strategy_id = "failing"
    calls = 0

    def evaluate(self, market):
        FailingStrategy.calls += 1
        raise RuntimeError("future strategy bug")


class MutatingStrategy(FutureStrategy):
    """Misbehaves by mutating its input; must not reach any other strategy."""
    strategy_id = "mutating"

    def evaluate(self, market):
        for row in market.rows:
            row["close"] = row["close"] * 2
        market.rows.clear()
        return super().evaluate(market)


class AdapterEquivalenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = g.load_fixtures()
        cls.golden = json.loads(g.SCANNER_GOLDEN.read_text(encoding="utf-8"))
        cls.strategy = TrendlineStrategy()

    def assertAdapterEquivalent(self, market: MarketInput, direct: dict):
        # `direct` is analyze_symbol's default (v3-labelled) output: the legacy strategy
        # reproduces it exactly, v4 differs only in the version label.
        self.assertEqual(g.canonical(LegacyTrendlineStrategy().evaluate(market)), g.canonical(direct))
        direct = g.as_version(direct, TrendlineStrategy.version)
        payload = self.strategy.evaluate(market)
        self.assertEqual(g.canonical(payload), g.canonical(direct))
        result = strategies.StrategyResult(self.strategy.strategy_id, self.strategy.version, payload)
        record = result.record()
        self.assertEqual(set(record) - set(direct), set(METADATA_FIELDS))
        self.assertEqual(g.canonical({key: record[key] for key in direct}), g.canonical(direct))
        self.assertEqual(record["strategy_id"], "trendline")

    def test_matches_analyze_symbol_and_the_golden_for_every_fixture(self):
        for fixture in self.fixtures:
            with self.subTest(fixture=fixture["name"]):
                direct = g.scan(fixture)
                self.assertEqual(json.loads(g.canonical(direct)), self.golden[fixture["name"]])
                self.assertAdapterEquivalent(market_input(fixture), direct)

    def test_matches_analyze_symbol_on_generated_series(self):
        for seed, direct in random_scans(150):
            sessions = [None, {"session": "London"}, {"session": "New York", "session_alignment": "aligned"}]
            market = MarketInput("SYN", walk(seed, 130, 900.0, 0.3 + (seed % 5) * 0.1), spread=0.01,
                                 session_context=sessions[seed % 3], higher_rows=walk(seed + 10**6, 80, 3600.0, 0.7))
            with self.subTest(seed=seed):
                self.assertAdapterEquivalent(market, direct)

    def test_forwards_defaults_and_does_not_mutate_input(self):
        fixture = next(f for f in self.fixtures if f["name"] == "real_XAUUSD")
        market = MarketInput(fixture["symbol"], copy.deepcopy(fixture["rows"]))
        before = copy.deepcopy(market)
        self.assertEqual(g.canonical(self.strategy.evaluate(market)),
                         g.canonical(g.as_version(scanner.analyze_symbol(fixture["symbol"], fixture["rows"]), TrendlineStrategy.version)))
        self.assertEqual(market, before)
        short = MarketInput("SYN", walk(1, 59, 900.0, 0.3))
        self.assertEqual(self.strategy.evaluate(short), scanner.analyze_symbol("SYN", walk(1, 59, 900.0, 0.3)))  # no version when too short

    def test_identity_matches_what_the_engine_reports(self):
        for fixture in self.fixtures:
            payload = self.strategy.evaluate(market_input(fixture))
            if "strategy_version" in payload:  # absent only for insufficient history
                self.assertEqual(payload["strategy_version"], TrendlineStrategy.version)
                self.assertEqual(payload["timeframe"], TrendlineStrategy.timeframe)
                self.assertEqual(tuple(payload["higher_timeframes"]), TrendlineStrategy.higher_timeframes)

    def test_contract_fields_read_the_trendline_decisions(self):
        for fixture in self.fixtures:
            payload = self.strategy.evaluate(market_input(fixture))
            result = strategies.StrategyResult("trendline", TrendlineStrategy.version, payload)
            with self.subTest(fixture=fixture["name"]):
                for name, key in CORE_FIELDS.items():
                    self.assertEqual(result.core(name), payload.get(key))
                self.assertEqual(result.confirmed, payload.get("strategy_valid") is True)


class RegistryIsolationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = next(f for f in g.load_fixtures() if f["name"] == "real_XAUUSD")
        self.expected = g.canonical(g.as_version(g.scan(self.fixture), TrendlineStrategy.version))

    def test_default_registry_has_three_live_strategies(self):
        # Trendline, Support & Resistance (Phase 6) and Trend / Momentum (Phase 10) are all LIVE
        # since Phase 10b; each stays independent (scoped by strategy_id).
        for registry in (strategies.REGISTRY, build_default_registry()):
            self.assertEqual(registry.registered(), ["trendline", "support_resistance", "trend_momentum"])
            self.assertEqual(registry.enabled(), ["trendline", "support_resistance", "trend_momentum"])
            self.assertEqual(registry.live(), ["trendline", "support_resistance", "trend_momentum"])
            self.assertEqual([registry.mode(s) for s in registry.registered()], ["LIVE", "LIVE", "LIVE"])

    def test_trendline_runs_through_the_registry(self):
        results = build_default_registry().evaluate(market_input(self.fixture))
        self.assertEqual(list(results), ["trendline", "support_resistance", "trend_momentum"])
        self.assertEqual([r.mode for r in results.values()], ["LIVE", "LIVE", "LIVE"])
        self.assertTrue(results["trendline"].ok)
        self.assertEqual(results["trendline"].strategy_version, "trendline-first-v4")
        self.assertEqual(g.canonical(results["trendline"].payload), self.expected)

    def test_disabled_strategy_produces_no_output_and_is_not_called(self):
        FailingStrategy.calls = 0
        registry = g.trendline_only_registry()
        registry.register(FailingStrategy())                 # registered disabled by default
        registry.disable("trendline")
        with mock.patch.object(scanner, "analyze_symbol", side_effect=AssertionError("called")):
            self.assertEqual(registry.evaluate(market_input(self.fixture)), {})
        registry.enable("trendline")
        self.assertEqual(list(registry.evaluate(market_input(self.fixture))), ["trendline"])
        self.assertEqual(FailingStrategy.calls, 0)

    def test_registering_a_future_strategy_leaves_trendline_unchanged(self):
        registry = build_default_registry()
        registry.register(FutureStrategy(), enabled=True)
        results = registry.evaluate(market_input(self.fixture))
        self.assertEqual(list(results), ["trendline", "support_resistance", "trend_momentum", "future"])
        self.assertEqual(g.canonical(results["trendline"].payload), self.expected)
        self.assertEqual(results["future"].record()["strategy_id"], "future")

    def test_failing_future_strategy_cannot_affect_trendline(self):
        for order in ("before", "after"):
            registry = StrategyRegistry()
            if order == "before":
                registry.register(FailingStrategy(), enabled=True)
            registry.register(TrendlineStrategy(), enabled=True)
            if order == "after":
                registry.register(FailingStrategy(), enabled=True)
            with self.subTest(order=order), self.assertLogs("trading_hub.strategies", "WARNING"):
                results = registry.evaluate(market_input(self.fixture))
                self.assertEqual(g.canonical(results["trendline"].payload), self.expected)
                self.assertFalse(results["failing"].ok)
                self.assertIsInstance(results["failing"].error, RuntimeError)
                self.assertIsNone(results["failing"].payload)

    def test_input_mutating_future_strategy_cannot_affect_trendline(self):
        registry = StrategyRegistry()
        registry.register(MutatingStrategy(), enabled=True)  # runs first
        registry.register(TrendlineStrategy(), enabled=True)
        market = market_input(copy.deepcopy(self.fixture))
        results = registry.evaluate(market)
        self.assertEqual(g.canonical(results["trendline"].payload), self.expected)
        self.assertEqual(market.rows, self.fixture["rows"])  # the caller's data is untouched too

    def test_duplicate_and_unknown_ids_are_rejected(self):
        registry = build_default_registry()
        with self.assertRaises(ValueError):
            registry.register(TrendlineStrategy())
        with self.assertRaises(KeyError):
            registry.enable("unknown")


class FakeMT5:
    """Just enough of the MetaTrader5 API for one market_snapshot() pass."""
    TIMEFRAME_M15, TIMEFRAME_H1 = 15, 60

    def __init__(self, fixtures):
        self.fixtures = {f["symbol"]: f for f in fixtures}

    def initialize(self):
        return True

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def symbol_info_tick(self, symbol):
        close = self.fixtures[symbol]["rows"][-1]["close"]
        return SimpleNamespace(bid=close - 0.1, ask=close + 0.1, time_msc=0, time=0)

    def symbol_info(self, symbol):
        return SimpleNamespace(last=0.0)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        fixture = self.fixtures[symbol]
        return fixture["rows"] if timeframe == self.TIMEFRAME_M15 else (fixture.get("higher_rows") or [])


class ScanLoopTests(unittest.TestCase):
    def test_market_snapshot_builds_markets_from_the_unmodified_trendline_payload(self):
        import main
        fixtures = [f for f in g.load_fixtures() if f["name"] in ("real_XAUUSD", "real_EURUSD", "synthetic_insufficient_data")]
        fixtures = [{**f, "symbol": s} for f, s in zip(fixtures, ("XAUUSD", "EURUSD", "GBPUSD"))]
        direct_calls, recorded = [], []
        real_analyze = scanner.analyze_symbol

        def spy(*args, **kwargs):
            payload = real_analyze(*args, **kwargs)
            direct_calls.append((args, kwargs, copy.deepcopy(payload)))
            return payload
        main._MT5_SESSION.update(initialized=False, initializations=0)
        with mock.patch.object(main, "mt5", FakeMT5(fixtures)), \
             mock.patch.object(main, "mt5_symbol", side_effect=lambda s: s if s in ("XAUUSD", "EURUSD", "GBPUSD") else None), \
             mock.patch.object(scanner, "analyze_symbol", side_effect=spy), \
             mock.patch.object(main, "record_markets", side_effect=lambda markets: recorded.append(copy.deepcopy(markets))), \
             mock.patch.object(main, "confirmation_events", return_value=[]), \
             mock.patch.object(main, "snapshots_by_observation_id", return_value={}), \
             mock.patch.object(main, "outcome_watch_snapshots", return_value=[]), \
             mock.patch.object(main, "list_records", return_value=[]), \
             mock.patch.object(main, "resolve_due_market_outcomes", return_value=[]):
            markets = main.market_snapshot()
        main._MT5_SESSION.update(initialized=False, initializations=0)
        self.assertEqual([m["symbol"] for m in markets], ["XAUUSD", "EURUSD", "GBPUSD"])
        self.assertEqual(len(direct_calls), 3)
        for market, (args, kwargs, payload) in zip(markets, direct_calls):
            # Same call the scan loop made before, and every payload field lands unchanged.
            self.assertEqual(args[0], market["broker_symbol"])
            # Same call as before plus the version label (Phase 9: trendline-first-v4).
            self.assertEqual(set(kwargs), {"spread", "session_context", "higher_rows", "strategy_version"})
            self.assertEqual(kwargs["strategy_version"], "trendline-first-v4")
            self.assertEqual(g.canonical({key: market[key] for key in payload}), g.canonical(payload))
            self.assertNotIn("strategy_id", market)
        self.assertEqual(len(recorded), 1)

    def test_trendline_failure_still_fails_the_scan_as_before(self):
        import main
        fixture = {**next(f for f in g.load_fixtures() if f["name"] == "real_XAUUSD"), "symbol": "XAUUSD"}
        main._MT5_SESSION.update(initialized=False, initializations=0)
        with mock.patch.object(main, "mt5", FakeMT5([fixture])), \
             mock.patch.object(main, "mt5_symbol", side_effect=lambda s: s if s == "XAUUSD" else None), \
             mock.patch.object(scanner, "analyze_symbol", side_effect=ZeroDivisionError("engine bug")), \
             mock.patch.object(main, "record_markets") as record, \
             self.assertLogs("trading_hub", "WARNING"):
            self.assertEqual(main.market_snapshot(), [])
        main._MT5_SESSION.update(initialized=False, initializations=0)
        record.assert_not_called()
        self.assertEqual(main._LAST_SCAN["status"], "SCAN_ERROR")
        self.assertEqual(main._LAST_SCAN["error"], "engine bug")


if __name__ == "__main__":
    unittest.main()
