"""Performance & Efficiency V1, Phase A: same results, less work.

- the radar serves the autonomous worker's latest scan and never scans itself;
  /api/health never waits for a scan in progress;
- market outcomes are read through an incremental index (no full re-parse);
- WATCH snapshots are read once per process (projection memo) with identical outcomes;
- read endpoints are cached until a source file changes;
- broker symbols are resolved once per MT5 session;
- strategies share one read-only market input with payloads identical to per-strategy copies.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import golden_support as g  # noqa: E402
import main  # noqa: E402
import observations  # noqa: E402
import outcomes  # noqa: E402
import smc_fixtures  # noqa: E402
import sr_fixtures  # noqa: E402
import tm_fixtures  # noqa: E402
from strategies import MarketInput, build_default_registry  # noqa: E402
from strategies.base import Strategy  # noqa: E402
from strategies.registry import StrategyRegistry, frozen_input, isolated_copy  # noqa: E402


def write_jsonl(path: Path, rows) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def outcome(setup_id, observation_id, horizon, label="WIN"):
    return {"record_type": "market_outcome", "setup_id": setup_id, "observation_id": observation_id,
            "horizon": horizon, "label": label, "label_definition": "target-invalidation-first-v1"}


class CachedRadarTests(unittest.TestCase):
    def setUp(self):
        self.saved = (dict(main._LAST_SCAN), dict(main._LAST_RESULT))

    def tearDown(self):
        main._LAST_SCAN.clear(); main._LAST_SCAN.update(self.saved[0])
        main._LAST_RESULT.clear(); main._LAST_RESULT.update(self.saved[1])

    def test_radar_and_context_never_start_a_scan(self):
        with mock.patch.object(main, "_market_snapshot", side_effect=AssertionError("must not scan")), \
             mock.patch.object(main, "fundamentals_snapshot", return_value={}):
            for _ in range(3):
                main.radar()
            main.context()

    def test_radar_serves_the_latest_worker_scan_with_freshness(self):
        markets = [{"symbol": "XAUUSD", "state": "WATCHING"}]

        def scan():
            main._LAST_SCAN.update(status="CONNECTED", completed_at="2026-10-05T06:00:00+00:00", error=None, elapsed_ms=1200.0)
            return markets
        before = main._LAST_RESULT["sequence"]
        with mock.patch.object(main, "_market_snapshot", side_effect=scan):
            self.assertIs(main.market_snapshot(), markets)        # the worker's call
        with mock.patch.object(main, "_market_snapshot", side_effect=AssertionError("must not scan")):
            response = main.radar()
        self.assertEqual(response["markets"], markets)
        self.assertTrue(response["live"])
        self.assertEqual(response["timestamp"], "2026-10-05T06:00:00+00:00")
        self.assertEqual(response["scan"]["sequence"], before + 1)
        self.assertEqual(response["scan"]["completed_at"], "2026-10-05T06:00:00+00:00")
        self.assertEqual(response["scan"]["source"], "autonomous_worker")
        now = datetime(2026, 10, 5, 6, 1, tzinfo=timezone.utc)
        self.assertEqual(main.latest_scan(now)[2]["status"], "FRESH")
        self.assertEqual(main.latest_scan(now + timedelta(hours=1))[2]["status"], "STALE")

    def test_before_the_first_scan_the_radar_is_empty_not_scanning(self):
        main._LAST_RESULT.update(markets=[], sequence=0, completed_at=None)
        main._LAST_SCAN.update(status="SCANNING", completed_at=None, error=None)
        response = main.radar()
        self.assertEqual((response["markets"], response["live"], response["engine_status"]), ([], False, "SCANNING"))
        self.assertEqual(response["scan"]["status"], "NOT_SCANNED")

    def test_health_and_radar_do_not_wait_for_a_scan_in_progress(self):
        held, release = threading.Event(), threading.Event()

        def hold():
            with main._SCAN_LOCK:
                held.set()
                release.wait(10)
        worker = threading.Thread(target=hold)
        worker.start()
        try:
            held.wait(5)
            done = {}
            reader = threading.Thread(target=lambda: done.update(radar=main.radar(), health=main.health()))
            # (index stats stubbed: health must not build the real 1 GB store's index here, which
            # alone can take longer than the 5 s budget and is not what this test measures)
            with mock.patch.object(main, "mt5", None), mock.patch.object(main, "observation_index_stats", return_value={}):
                reader.start()
                reader.join(5)
            self.assertFalse(reader.is_alive(), "health/radar blocked on the scan lock")
            self.assertIn("last_scan", done["health"])
        finally:
            release.set()
            worker.join()


class OutcomeIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "market_outcomes.jsonl"
        write_jsonl(self.path, [outcome("stp_a", "obs_a", "15m"), outcome("stp_b", "obs_b", "1h", "LOSS"),
                                outcome("stp_a", "obs_a", "1h", "NO_HIT"), {"record_type": "market_outcome", "setup_id": 7}])

    def tearDown(self):
        self.tmp.cleanup()

    def present_from_full_read(self):
        return {(r.get("setup_id"), r.get("observation_id"), r.get("horizon"), r.get("label_definition"))
                for r in outcomes.list_records(self.path)}

    def test_index_answers_exactly_what_the_full_read_answers(self):
        self.assertEqual(outcomes.present_outcome_keys(self.path), self.present_from_full_read())
        for setup_id in ("stp_a", "stp_b", "missing"):
            self.assertEqual(outcomes.outcomes_for_setup(setup_id, self.path), outcomes.list_records(self.path, setup_id))
        self.assertEqual(outcomes.outcomes_for_setups(["stp_b", "stp_a"], self.path, exact=True),
                         [r for r in outcomes.list_records(self.path) if r.get("setup_id") in ("stp_a", "stp_b")])
        # str(setup_id) matching, as the reports key outcomes
        self.assertEqual(outcomes.outcomes_for_setups(["7"], self.path), [{"record_type": "market_outcome", "setup_id": 7}])

    def test_appends_are_picked_up_incrementally_and_partial_lines_wait(self):
        index = outcomes.market_outcome_index(self.path)
        outcomes.present_outcome_keys(self.path)
        consumed = index.offset
        write_jsonl(self.path, [outcome("stp_c", "obs_c", "4h")])
        self.assertEqual(outcomes.present_outcome_keys(self.path), self.present_from_full_read())
        self.assertGreater(index.offset, consumed)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(outcome("stp_d", "obs_d", "4h"))[:20])          # an append in progress
        self.assertNotIn(("stp_d", "obs_d", "4h", "target-invalidation-first-v1"), outcomes.present_outcome_keys(self.path))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(outcome("stp_d", "obs_d", "4h"))[20:] + "\n")
        self.assertIn(("stp_d", "obs_d", "4h", "target-invalidation-first-v1"), outcomes.present_outcome_keys(self.path))

    def test_returned_present_set_is_a_copy(self):
        keys = outcomes.present_outcome_keys(self.path)
        keys.add(("x",))
        self.assertNotIn(("x",), outcomes.present_outcome_keys(self.path))

    def test_outcomes_route_by_setup_ids(self):
        with mock.patch.object(main, "MARKET_OUTCOMES_FILE", self.path):
            subset = main.market_outcomes(setup_ids="stp_b,stp_a,stp_b")["outcomes"]
            single = main.market_outcomes(setup_id="stp_b")["outcomes"]
            everything = main.market_outcomes()["outcomes"]
        self.assertEqual([r["setup_id"] for r in subset], ["stp_a", "stp_b", "stp_a"])     # file order
        self.assertEqual(single, outcomes.list_records(self.path, "stp_b"))
        self.assertEqual(everything, outcomes.list_records(self.path))
        from fastapi import HTTPException
        with mock.patch.object(main, "MARKET_OUTCOMES_FILE", self.path), self.assertRaises(HTTPException):
            main.market_outcomes(setup_ids=",".join(f"s{i}" for i in range(main.MAX_OUTCOME_SETUP_IDS + 1)))


def watch_snapshot(observation_id, observed_at, *, valid=True, symbol="XAUUSD", setup_id="stp_w"):
    return {"record_type": "setup_snapshot", "setup_id": setup_id, "observation_id": observation_id,
            "observed_at": observed_at, "source_timestamp": observed_at, "symbol": symbol, "timeframe": "M15",
            "direction": "LONG", "reference_price": 100.0, "proposed_take_profit": 101.0 if valid else None,
            "proposed_stop_loss": 99.0, "invalidation_price": 99.0, "features": {"atr": 1.0},
            "rule_evidence": {"strategy_valid": False, "reason": "watching"},
            "time_provenance": {"timezone_normalization_status": "VERIFIED", "source_time_basis": "UTC",
                                "bar_open_time": {"raw": 1}}}


class ResolverEquivalenceTests(unittest.TestCase):
    """The resolver's early skips change no output."""
    NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)

    def bars(self, start: datetime, count: int):
        base = start.timestamp()
        return [{"time": base + i * 900, "open": 100.0, "high": 100.2 + (i % 7) * 0.2, "low": 99.8 - (i % 5) * 0.2,
                 "close": 100.0} for i in range(count)]

    def test_window_skip_and_present_keys_give_identical_outcomes(self):
        observed = [self.NOW - timedelta(hours=h, minutes=7) for h in (1, 3, 5, 20, 26, 30, 50, 80)]
        snapshots = [watch_snapshot(f"obs_{i}", o.isoformat(), setup_id=f"stp_{i}") for i, o in enumerate(observed)]
        bars = {"XAUUSD": self.bars(self.NOW - timedelta(hours=28), 28 * 4)}
        existing = [outcome("stp_1", "obs_1", "15m")]
        strip = lambda rows: [{k: v for k, v in r.items() if k != "outcome_id"} for r in rows]  # noqa: E731
        horizons = ("15m", "1h", "4h", "24h")
        with mock.patch.object(outcomes, "_nothing_to_label", return_value=False):
            reference = outcomes.resolve_due_market_outcomes([], {}, bars, existing, horizons, now=self.NOW,
                                                             watch_snapshots=snapshots)
        fast = outcomes.resolve_due_market_outcomes([], {}, bars, [], horizons, now=self.NOW, watch_snapshots=snapshots,
                                                    present={(r["setup_id"], r["observation_id"], r["horizon"],
                                                              r["label_definition"]) for r in existing})
        self.assertGreater(len(reference), 0)
        self.assertEqual(strip(fast), strip(reference))

    def test_skip_only_when_derive_returns_none(self):
        bars = self.bars(self.NOW - timedelta(hours=10), 40)
        earliest = outcomes._earliest_bar_epoch(bars)
        for hours_ago in (0.1, 0.5, 3, 11, 12, 20, 23.9, 35):
            snapshot = watch_snapshot("o", (self.NOW - timedelta(hours=hours_ago)).isoformat())
            observed = datetime.fromisoformat(snapshot["observed_at"])
            for horizon in ("15m", "1h", "4h", "24h"):
                if outcomes._nothing_to_label(observed, horizon, "M15", earliest, self.NOW):
                    self.assertIsNone(outcomes.derive_market_outcome(snapshot, horizon, bars, "M15", target_price=101.0,
                                                                     invalidation_price=99.0, now=self.NOW))
        self.assertIsNone(outcomes._earliest_bar_epoch([{"time": "2026-10-05T00:00:00+00:00"}]))


class WatchMemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = g.isolated_store(observations, self.root)
        self.store.__enter__()
        now = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)
        write_jsonl(observations.LOG_FILE, [watch_snapshot("obs_v", now.isoformat()),
                                           watch_snapshot("obs_i", now.isoformat(), valid=False, setup_id="stp_i")])

    def tearDown(self):
        self.store.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_rows_are_read_once_and_projected_to_what_the_resolver_reads(self):
        index = observations._observation_index()
        with mock.patch.object(index, "load", wraps=index.load) as load:
            first = observations.outcome_watch_snapshots(set(), {"XAUUSD"}, set(), ("1h",))
            second = observations.outcome_watch_snapshots(set(), {"XAUUSD"}, set(), ("1h",))
        self.assertEqual([row["observation_id"] for row in first], ["obs_v"])          # no valid barriers: skipped
        self.assertEqual(first, second)
        self.assertEqual(sum(len(list(call.args[0])) for call in load.call_args_list if call.args), 2)  # both rows, once
        self.assertNotIn("features", first[0])
        self.assertEqual(first[0]["time_provenance"], {"timezone_normalization_status": "VERIFIED", "source_time_basis": "UTC"})
        # a row whose horizons are all present is no longer returned
        present = {("stp_w", "obs_v", "1h", "target-invalidation-first-v1")}
        self.assertEqual(observations.outcome_watch_snapshots(set(), {"XAUUSD"}, present, ("1h",)), [])

    def test_projection_resolves_exactly_like_the_full_row(self):
        full = [row for row in observations.all_observations() if row["observation_id"] == "obs_v"]
        projected = observations.outcome_watch_snapshots(set(), {"XAUUSD"}, set(), ("15m", "1h", "4h"))
        now = datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)
        base = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc).timestamp()
        bars = {"XAUUSD": [{"time": base + i * 900, "open": 100.0, "high": 100.3 + i * 0.05, "low": 99.9, "close": 100.1}
                           for i in range(1, 40)]}
        strip = lambda rows: [{k: v for k, v in r.items() if k != "outcome_id"} for r in rows]  # noqa: E731
        expected = outcomes.resolve_due_market_outcomes([], {}, bars, [], ("15m", "1h", "4h"), now=now, watch_snapshots=full)
        actual = outcomes.resolve_due_market_outcomes([], {}, bars, [], ("15m", "1h", "4h"), now=now, watch_snapshots=projected)
        self.assertGreater(len(expected), 0)
        self.assertEqual(strip(actual), strip(expected))


class ReadCacheTests(unittest.TestCase):
    def test_stamped_cache_recomputes_after_a_source_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.jsonl"
            write_jsonl(path, [{"a": 1}])
            cache, builds = main._StampedCache(), []
            build = lambda: builds.append(1) or len(builds)  # noqa: E731
            key = lambda: ("k", main._stamps(path))  # noqa: E731
            self.assertEqual(cache.get(key(), build), 1)
            self.assertEqual(cache.get(key(), build), 1)
            write_jsonl(path, [{"a": 2}])
            self.assertEqual(cache.get(key(), build), 2)

    def test_setup_episode_feed_matches_a_fresh_read_after_every_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with g.isolated_store(observations, root):
                t0 = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
                write_jsonl(observations.LOG_FILE, [{**watch_snapshot("o1", t0.isoformat(), setup_id="s1"), "lifecycle_state": "DETECTED"}])

                def fresh():
                    observations._EPISODE_FEED.clear()
                    return observations.setup_episodes("all", 50)
                steps = [
                    lambda: write_jsonl(observations.LOG_FILE, [{**watch_snapshot("o2", (t0 + timedelta(minutes=1)).isoformat(), setup_id="s2"), "lifecycle_state": "DETECTED"}]),
                    lambda: write_jsonl(observations.LOG_FILE, [{**watch_snapshot("o3", (t0 + timedelta(minutes=2)).isoformat(), setup_id="s1"), "lifecycle_state": "DEVELOPING"}]),
                    lambda: write_jsonl(observations.LIFECYCLE_FILE, [{"setup_id": "s2", "to_state": "EXPIRED", "occurred_at": (t0 + timedelta(minutes=3)).isoformat()}]),
                    lambda: write_jsonl(observations.CONFIRMATIONS_FILE, [{"setup_id": "s1", "observation_id": "o3", "confirmed_at": (t0 + timedelta(minutes=2)).isoformat()}]),
                ]
                observations.setup_episodes("all", 50)            # warm the cache
                for step in steps:
                    step()
                    cached = observations.setup_episodes("all", 50)
                    self.assertEqual(cached, fresh())
                self.assertEqual({row["setup_id"]: row["bucket"] for row in cached}, {"s1": "confirmed", "s2": "closed"})


class SymbolCacheTests(unittest.TestCase):
    class Broker:
        def __init__(self, names):
            self.names, self.probes = set(names), 0

        def symbol_select(self, name, enable):
            self.probes += 1
            return name in self.names

        def symbol_info(self, name):
            return SimpleNamespace() if name in self.names else None

        def symbols_get(self):
            return [SimpleNamespace(name=name) for name in self.names]

    def test_resolution_is_cached_per_terminal_session_and_forgotten_on_failure(self):
        broker = self.Broker({"USTEC"})
        with mock.patch.object(main, "mt5", broker):
            self.assertEqual(main.mt5_symbol("NAS100"), "USTEC")
            probes = broker.probes
            self.assertEqual(main.mt5_symbol("NAS100"), "USTEC")
            self.assertEqual(broker.probes, probes, "a cached symbol is not probed again")
            main.forget_mt5_symbol("NAS100")
            main.mt5_symbol("NAS100")
            self.assertGreater(broker.probes, probes)
            probes = broker.probes
            main._MT5_SESSION["initializations"] += 1            # reconnect: resolve again
            main.mt5_symbol("NAS100")
            self.assertGreater(broker.probes, probes)
            self.assertIsNone(main.mt5_symbol("GER40"))
            probes = broker.probes
            self.assertIsNone(main.mt5_symbol("GER40"))
            self.assertEqual(broker.probes, probes, "a failed resolution waits SYMBOL_RETRY_SECONDS")
        with mock.patch.object(main, "mt5", self.Broker({"DE40"})):
            self.assertEqual(main.mt5_symbol("GER40"), "DE40", "another terminal never reuses the cache")


class SharedInputTests(unittest.TestCase):
    """The shared read-only input yields byte-identical payloads to per-strategy copies."""

    @staticmethod
    def with_context(fixture):
        h1 = fixture["higher_rows"]
        bars = {"M15": fixture["rows"], "H1": h1, "H4": h1[::4], "D1": h1[::24]}
        return MarketInput(fixture["symbol"], fixture["rows"], spread=fixture.get("spread", 0.0),
                           session_context=fixture.get("session_context"), higher_rows=h1, bars=bars)

    def inputs(self):
        yield from (self.with_context(fixture) for fixture in g.load_fixtures() if fixture.get("higher_rows"))
        yield tm_fixtures.scenario()
        yield tm_fixtures.scenario(trigger=False)
        for frames in (smc_fixtures.bullish_bos(), smc_fixtures.bullish_choch(), smc_fixtures.bearish(smc_fixtures.bullish_bos())):
            yield MarketInput("XAUUSD", frames["M15"], higher_rows=frames["H1"], bars=frames)
        for m15 in (sr_fixtures.support_ending("bounce"), sr_fixtures.resistance_rejection()):
            bars = {"M15": m15, "H1": sr_fixtures.range_h1(), "H4": sr_fixtures.htf_bars(14400), "D1": sr_fixtures.htf_bars(86400)}
            yield MarketInput("XAUUSD", m15, higher_rows=bars["H1"], bars=bars)

    def test_payloads_identical_to_isolated_copies_and_json_clean(self):
        registry = build_default_registry()
        confirmed = 0
        for market in self.inputs():
            shared = registry.evaluate(market)
            for strategy_id, result in shared.items():
                expected = registry.get(strategy_id).evaluate(isolated_copy(market))
                self.assertTrue(result.ok, (market.symbol, strategy_id, result.error))
                # json.dumps without default= fails on any read-only bar leaking into a payload
                self.assertEqual(json.dumps(result.payload, sort_keys=True), json.dumps(expected, sort_keys=True))
                confirmed += result.payload.get("strategy_valid") is True
        self.assertGreater(confirmed, 0, "the comparison must include confirmed setups")

    def test_shared_input_is_read_only_and_the_caller_is_untouched(self):
        fixture = g.load_fixtures()[0]
        market = self.with_context(json.loads(json.dumps(fixture)))
        frozen = frozen_input(market)
        with self.assertRaises(TypeError):
            frozen.rows[0]["close"] = 0.0
        with self.assertRaises(AttributeError):
            frozen.rows.append({})
        with self.assertRaises(TypeError):
            frozen.bars["M15"] = []

        class Mutating(Strategy):
            strategy_id, version, timeframe, lifecycle = "mutating", "m-v1", "M15", "m"

            def evaluate(self, market):
                market.bars["M15"][0]["close"] = 0.0
                return {"state": "WATCHING"}

        class Reader(Strategy):
            strategy_id, version, timeframe, lifecycle = "reader", "r-v1", "M15", "r"

            def evaluate(self, market):
                return {"state": "WATCHING", "first_close": market.bars["M15"][0]["close"]}
        registry = StrategyRegistry()
        registry.register(Mutating(), enabled=True)
        registry.register(Reader(), enabled=True)
        with self.assertLogs("trading_hub.strategies", "WARNING"):
            results = registry.evaluate(market)
        self.assertIsInstance(results["mutating"].error, TypeError)
        self.assertEqual(results["reader"].payload["first_close"], fixture["rows"][0]["close"])
        self.assertEqual(market.rows[0]["close"], fixture["rows"][0]["close"])


if __name__ == "__main__":
    unittest.main()
