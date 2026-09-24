"""Phase 5: official 10-instrument universe and the market-data context.

A fake broker exposes IC Markets' symbol names (GER40 -> DE40, NAS100 -> USTEC)
and M15/H1/H4/D1 bars with tick_volume, built from the real MT5 captures in
tests/fixtures/scanner. Covers: aliases, the configurable watchlist, H4/D1 and
tick_volume reaching strategies, missing/unsupported timeframes, context
compatibility, and the trendline strategy producing identical markets and
records whether or not the extra context is available.
"""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g  # noqa: E402

import main  # noqa: E402
import market_data  # noqa: E402
import observations  # noqa: E402
import strategies  # noqa: E402
from strategies import MarketInput, Strategy, StrategyRegistry, TrendlineStrategy  # noqa: E402

IC_MARKETS = {"XAUUSD": "XAUUSD", "BTCUSD": "BTCUSD", "ETHUSD": "ETHUSD", "EURUSD": "EURUSD", "GBPUSD": "GBPUSD",
              "GBPJPY": "GBPJPY", "USDJPY": "USDJPY", "NAS100": "USTEC", "US500": "US500", "GER40": "DE40"}


def fixture_for(symbol: str) -> dict:
    return next(f for f in g.load_fixtures() if f["name"] == "real_" + symbol)


def with_volume(rows, step):
    return [{**row, "tick_volume": 100 + (index * 7) % 50, "spread": 3, "real_volume": 0} for index, row in enumerate(rows)][:: max(1, step)]


class FakeBroker:
    """Enough of MetaTrader5 for mt5_symbol() and one market_snapshot() pass."""

    def __init__(self, names: dict[str, str], timeframes=("M15", "H1", "H4", "D1"), no_data=(), bars_from=None):
        # bars_from: product -> fixture whose captured bars back it (for symbols without a capture)
        self.fixtures = {broker: fixture_for((bars_from or {}).get(product, product)) for product, broker in names.items()}
        self.no_data = set(no_data)
        self.requests = []
        for name, code in {"M15": 15, "H1": 60, "H4": 240, "D1": 1440}.items():
            if name in timeframes:
                setattr(self, "TIMEFRAME_" + name, code)

    def initialize(self):
        return True

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def symbol_select(self, name, enable):
        return name in self.fixtures

    def symbol_info(self, name):
        return SimpleNamespace(last=0.0) if name in self.fixtures else None

    def symbols_get(self):
        return [SimpleNamespace(name=name) for name in self.fixtures]

    def symbol_info_tick(self, name):
        close = self.fixtures[name]["rows"][-1]["close"]
        return SimpleNamespace(bid=close - 0.1, ask=close + 0.1, time_msc=0, time=0)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        self.requests.append((symbol, timeframe, count))
        name = {15: "M15", 60: "H1", 240: "H4", 1440: "D1"}[timeframe]
        if name in self.no_data:
            return None
        fixture = self.fixtures[symbol]
        if name == "M15":
            return with_volume(fixture["rows"], 1)[-count:]
        if name == "H1":
            return with_volume(fixture["higher_rows"], 1)[-count:]
        # H4/D1: every 4th / 24th H1 bar, as a stand-in (only availability and fields matter here).
        return with_volume(fixture["higher_rows"], 4 if name == "H4" else 24)[-count:]


class Capture(Strategy):
    """Records the MarketInput it receives; declares the context it needs."""
    strategy_id, version, timeframe, lifecycle = "capture", "capture-v1", "M15", "capture"
    data_requirements = {"M15": 300, "H1": 160, "H4": 200, "D1": 200}
    seen: list = []

    def evaluate(self, market):
        Capture.seen.append(market)
        return {"state": "WATCHING", "direction": None, "strategy_valid": False, "score": 0, "score_breakdown": {}}


def run_scan(broker: FakeBroker, registry: StrategyRegistry | None = None, watchlist=None, root: Path | None = None):
    patches = [mock.patch.object(main, "mt5", broker), mock.patch.object(main, "datetime", g.FrozenClock.make()),
               mock.patch.object(main, "WATCHLIST", watchlist or list(main.OFFICIAL_UNIVERSE)),
               mock.patch.object(main, "resolve_due_market_outcomes", return_value=[])]
    if registry is not None:
        patches.append(mock.patch.object(main, "STRATEGIES", registry))
    main._MT5_SESSION.update(initialized=False, initializations=0)
    tmp = tempfile.TemporaryDirectory() if root is None else None
    store = Path(tmp.name) if tmp else root
    try:
        with g.isolated_store(observations, store):
            for patch in patches:
                patch.start()
            try:
                markets = main.market_snapshot()
            finally:
                for patch in reversed(patches):
                    patch.stop()
        files = {name: (store / name).read_bytes() for name in g.PERSISTED_FILES if (store / name).exists()}
    finally:
        main._MT5_SESSION.update(initialized=False, initializations=0)
        if tmp:
            tmp.cleanup()
    return markets, files


class UniverseTests(unittest.TestCase):
    def test_official_universe_and_configurable_extras(self):
        self.assertEqual(main.OFFICIAL_UNIVERSE, ("XAUUSD", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD",
                                                  "GBPJPY", "USDJPY", "NAS100", "US500", "GER40"))
        self.assertEqual(set(main.OFFICIAL_UNIVERSE), set(g.OFFICIAL_SCAN))
        for symbol in main.OFFICIAL_UNIVERSE:
            self.assertIn(symbol, main.SYMBOL_ALIASES)
        self.assertEqual(main.configured_watchlist(None)[:10], list(main.OFFICIAL_UNIVERSE))
        self.assertEqual(main.configured_watchlist(None)[10:], list(main.DEFAULT_EXTRA_SYMBOLS))
        self.assertEqual(main.configured_watchlist(""), list(main.OFFICIAL_UNIVERSE))
        self.assertEqual(main.configured_watchlist(" xagusd, GER40 ,,"), [*main.OFFICIAL_UNIVERSE, "XAGUSD"])

    def test_all_official_instruments_resolve_to_the_broker_symbols(self):
        with mock.patch.object(main, "mt5", FakeBroker(IC_MARKETS)):
            resolved = {symbol: main.mt5_symbol(symbol) for symbol in main.OFFICIAL_UNIVERSE}
        self.assertEqual(resolved, IC_MARKETS)
        self.assertEqual((resolved["GER40"], resolved["NAS100"]), ("DE40", "USTEC"))

    def test_ger40_alias_variants_and_no_false_match(self):
        for broker_name in ("GER40", "DE40", "DAX40", "DE40.r"):
            with self.subTest(broker=broker_name), mock.patch.object(main, "mt5", FakeBroker({"GER40": broker_name})):
                self.assertEqual(main.mt5_symbol("GER40"), broker_name)
        with mock.patch.object(main, "mt5", FakeBroker({"GER40": "GER30"})):
            self.assertIsNone(main.mt5_symbol("GER40"), "an unrelated index is never substituted")

    def test_markets_keep_product_symbols_and_report_their_data(self):
        markets, _ = run_scan(FakeBroker(IC_MARKETS))
        self.assertEqual([m["symbol"] for m in markets], list(main.OFFICIAL_UNIVERSE))
        by_symbol = {m["symbol"]: m for m in markets}
        self.assertEqual((by_symbol["GER40"]["broker_symbol"], by_symbol["NAS100"]["broker_symbol"]), ("DE40", "USTEC"))
        for market in markets:
            with self.subTest(symbol=market["symbol"]):
                data = market["market_data"]
                self.assertEqual(data["universe"], "OFFICIAL")
                self.assertEqual(set(data["timeframes"]), {"M15", "H1", "H4", "D1"})
                self.assertEqual((data["timeframes"]["M15"], data["timeframes"]["H1"]), (300, 160))
                self.assertEqual(data["unavailable_timeframes"], {})
                self.assertEqual(set(data["tick_volume"].values()), {True})
        extra, _ = run_scan(FakeBroker({**IC_MARKETS, "XAGUSD": "XAGUSD"}, bars_from={"XAGUSD": "XAUUSD"}),
                            watchlist=["XAUUSD", "XAGUSD"])
        self.assertEqual([m["market_data"]["universe"] for m in extra], ["OFFICIAL", "EXTRA"])


class ContextTests(unittest.TestCase):
    def setUp(self):
        Capture.seen = []

    def registry(self, *extra):
        registry = strategies.build_default_registry()
        for strategy in extra:
            registry.register(strategy, enabled=True)
        return registry

    def test_h4_d1_and_tick_volume_reach_strategies_while_trendline_rows_stay_ohlc(self):
        broker = FakeBroker({"GER40": "DE40"})
        run_scan(broker, self.registry(Capture()), watchlist=["GER40"])
        requests = [request[1:] for request in broker.requests if request[0] == "DE40"]
        seen = Capture.seen[0]
        self.assertEqual({tf: len(rows) for tf, rows in seen.bars.items()}, {"M15": 300, "H1": 160, "H4": 40, "D1": 7})
        source = broker.copy_rates_from_pos("DE40", 240, 0, 200)
        self.assertEqual([bar["tick_volume"] for bar in seen.bars["H4"]], [rate["tick_volume"] for rate in source])
        self.assertTrue(all(set(bar) == {"time", "open", "high", "low", "close", "tick_volume"} for rows in seen.bars.values() for bar in rows),
                        "no field is invented or dropped (spread/real_volume are not part of a bar)")
        self.assertEqual(market_data.ohlc_rows(seen.bars["M15"]), [dict(row) for row in seen.rows])
        self.assertTrue(all(set(row) == set(market_data.OHLC) for row in seen.rows), "trendline rows carry OHLC only")
        # M15/H1 are fetched once (300/160) and reused; H4/D1 once each.
        self.assertEqual(requests, [(15, 300), (60, 160), (240, 200), (1440, 200)])

    def test_bars_keep_broker_tick_volume_and_never_invent_it(self):
        rates = np.array([(1.0, 1.0, 2.0, 0.5, 1.5, 42, 3, 0)], dtype=[("time", "<i8"), ("open", "<f8"), ("high", "<f8"),
            ("low", "<f8"), ("close", "<f8"), ("tick_volume", "<u8"), ("spread", "<i4"), ("real_volume", "<u8")])
        self.assertEqual(market_data.bars_from_rates(rates), [{"time": 1.0, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "tick_volume": 42}])
        bare = np.array([(1.0, 1.0, 2.0, 0.5, 1.5)], dtype=[("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8")])
        self.assertNotIn("tick_volume", market_data.bars_from_rates(bare)[0])
        self.assertNotIn("tick_volume", market_data.bars_from_rates([{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1}])[0])
        self.assertEqual(market_data.summary({"M15": market_data.bars_from_rates(bare)}, {}, True)["tick_volume"], {"M15": False})

    def test_missing_and_unsupported_timeframes_are_reported_not_faked(self):
        class NeedsMore(Capture):
            strategy_id = "needs_more"
            data_requirements = {"M15": 300, "D1": 200, "X9": 10}
        broker = FakeBroker({"GER40": "DE40"}, timeframes=("M15", "H1", "H4", "D1"), no_data=("D1",))
        markets, _ = run_scan(broker, self.registry(NeedsMore()), watchlist=["GER40"])
        market = markets[0]
        self.assertEqual(market["market_data"]["unavailable_timeframes"], {"D1": "NO_DATA", "X9": "UNSUPPORTED_TIMEFRAME"})
        entries = {entry["strategy_id"]: entry for entry in market["strategies"]}
        self.assertEqual((entries["needs_more"]["status"], entries["needs_more"]["error"]), ("ERROR", "MissingMarketData"))
        self.assertEqual(entries["trendline"]["status"], "OK", "a strategy's missing data never blocks another")
        self.assertEqual(Capture.seen, [], "a strategy is not run without its declared data")
        # Fetch failures are reported too; an older terminal without H4/D1 constants marks them unsupported.
        failing = SimpleNamespace(TIMEFRAME_H4=240, copy_rates_from_pos=mock.Mock(side_effect=RuntimeError("IPC")))
        self.assertEqual(market_data.fetch_timeframes(failing, "DE40", {"H4": 200, "D1": 200})[1],
                         {"H4": "FETCH_FAILED", "D1": "UNSUPPORTED_TIMEFRAME"})

    def test_market_input_without_context_still_works(self):
        fixture = fixture_for("XAUUSD")
        legacy_input = MarketInput(fixture["symbol"], fixture["rows"], higher_rows=fixture["higher_rows"])
        self.assertEqual((dict(legacy_input.bars), dict(legacy_input.unavailable_timeframes)), ({}, {}))
        results = self.registry(Capture()).evaluate(legacy_input)
        self.assertTrue(results["trendline"].ok and results["capture"].ok, "no context collected: requirements unchecked")
        self.assertEqual(g.canonical(results["trendline"].payload), g.canonical(g.scan({**fixture, "spread": 0.0, "session_context": None})))
        self.assertEqual(TrendlineStrategy.data_requirements, {"M15": 300, "H1": 160})
        self.assertEqual(market_data.plan_for(strategies.REGISTRY), {"M15": 300, "H1": 160, "H4": 200, "D1": 200})

    def test_trendline_markets_and_records_unchanged_by_the_extra_context(self):
        # Trendline in isolation (shadow strategies may legitimately use the extra context).
        with_context = run_scan(FakeBroker(IC_MARKETS), g.trendline_only_registry())
        without_context = run_scan(FakeBroker(IC_MARKETS, timeframes=("M15", "H1")), g.trendline_only_registry())
        strip = lambda markets: [{k: v for k, v in m.items() if k != "market_data"} for m in markets]  # noqa: E731
        self.assertEqual(g.canonical(strip(with_context[0])), g.canonical(strip(without_context[0])))
        self.assertEqual(with_context[1], without_context[1], "persisted records are byte-identical")
        self.assertEqual(without_context[0][0]["market_data"]["unavailable_timeframes"],
                         {"H4": "UNSUPPORTED_TIMEFRAME", "D1": "UNSUPPORTED_TIMEFRAME"})
        # And each market's trendline fields are analyze_symbol's output for the same M15/H1 rows.
        spy_calls = []
        real = main.analyze_symbol

        def spy(*args, **kwargs):
            payload = real(*args, **kwargs)
            spy_calls.append(copy.deepcopy(payload))
            return payload
        with mock.patch("scanner.analyze_symbol", side_effect=spy):
            markets, _ = run_scan(FakeBroker(IC_MARKETS))
        for market, payload in zip(markets, spy_calls):
            self.assertEqual(g.canonical({k: market[k] for k in payload}), g.canonical(payload))


if __name__ == "__main__":
    unittest.main()
