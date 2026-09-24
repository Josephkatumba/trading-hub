"""Phase 3: strategy-aware persistence and lifecycle isolation.

Fake second strategies ("sr", "fake") stand in for future strategies; no real
S/R, SMC, ICT or CRT logic exists. Covers: read-time mapping of historical
records, strategy-scoped episodes and suppression (indexed and full-row paths),
strategy_id on snapshots/confirmations/episodes, strategy_version from the
registered strategy, the strategy_evidence container, the v3 observation index,
coexistence, failure isolation through the scan loop, one confirmation per
setup per strategy, unchanged outcome labels and per-strategy performance.
"""
from __future__ import annotations

import copy
import json
import math
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g  # noqa: E402

import legacy_observations as legacy  # noqa: E402
import observations  # noqa: E402
import strategies  # noqa: E402
from outcomes import resolve_due_market_outcomes  # noqa: E402
from performance import performance_report  # noqa: E402
from strategies import Strategy, StrategyRegistry, TrendlineStrategy, record_strategy_id  # noqa: E402
from test_strategy_isolation import IsolationTestCase, Store, market  # noqa: E402
from test_strategy_registry import FakeMT5  # noqa: E402


class OldRecordMappingTests(unittest.TestCase):
    def test_records_without_strategy_id_map_to_trendline(self):
        for setup_type in ("BREAK", "REVERSAL", "WATCHING", "GENERAL", None):
            with self.subTest(setup_type=setup_type):
                self.assertEqual(record_strategy_id({"record_type": "setup_snapshot", "setup_type": setup_type}), "trendline")
        self.assertEqual(record_strategy_id({"symbol": "EURUSD", "state": "DEVELOPING"}), "trendline")  # pre-episode row
        self.assertEqual(record_strategy_id({"record_type": "setup_confirmation", "setup_id": "stp"}), "trendline")
        self.assertEqual(record_strategy_id({"strategy_id": "sr"}), "sr")

    def test_historical_store_reads_unchanged_with_mapped_strategy_and_same_archive_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            # A store written entirely by the pre-strategy implementation.
            files = g.run_persistence(legacy, Path(tmp) / "old")
            self.assertEqual(g.jsonl_strategy_fields(b"".join(files.values())), [])
            root = Path(tmp) / "read"
            root.mkdir()
            for name, data in files.items():
                (root / name).write_bytes(data)
            before = {name: (root / name).read_bytes() for name in g.PERSISTED_FILES}
            with g.isolated_store(observations, root), g.isolated_store(legacy, root):
                for bucket in ("current", "confirmed", "closed"):
                    new, old = observations.setup_episodes(bucket, 500), legacy.setup_episodes(bucket, 500)
                    with self.subTest(bucket=bucket):
                        self.assertEqual(len(new), len(old))
                        self.assertEqual({row["strategy_id"] for row in new} - {"trendline"}, set())
                        # setup_type still tells BREAK / REVERSAL / WATCHING apart.
                        self.assertEqual([row.get("setup_type") for row in new], [row.get("setup_type") for row in old])
                self.assertIn("WATCHING", {row.get("setup_type") for row in observations.setup_episodes("all", 500)})
            # Reading never rewrites historical records.
            self.assertEqual({name: (root / name).read_bytes() for name in g.PERSISTED_FILES}, before)


class PersistedStrategyFieldTests(IsolationTestCase):
    def test_snapshots_carry_strategy_id_version_evidence_and_identity(self):
        evidence = {"zone": [2630.0, 2640.0], "touches": 3, "note": "fake strategy evidence"}
        self.store.scan(market("LONG"), {**market("SHORT", "sr", anchors=None), "strategy_evidence": evidence,
                                         "strategy_version": "sr-v1"})
        snapshots = {s["strategy_id"]: s for s in self.store.records("setup_observations.jsonl")}
        self.assertEqual(set(snapshots), {"trendline", "sr"})
        self.assertEqual(snapshots["trendline"]["strategy_evidence"], {})
        self.assertEqual(snapshots["sr"]["strategy_evidence"], evidence)
        self.assertEqual(snapshots["trendline"]["strategy_version"], "trendline-first-v3")
        self.assertEqual(snapshots["sr"]["strategy_version"], "sr-v1")  # unregistered: what the market reports
        for strategy_id, snapshot in snapshots.items():
            self.assertEqual(snapshot["episode_identity"]["strategy_id"], strategy_id)

    def test_strategy_version_comes_from_the_registered_strategy(self):
        class Fake(Strategy):
            strategy_id, version, timeframe, lifecycle = "fake", "fake-v7", "M15", "fake"

            def evaluate(self, market):
                return {}
        registry = strategies.build_default_registry()
        registry.register(Fake())
        with mock.patch.object(observations, "STRATEGIES", registry):
            self.store.scan({**market("LONG"), "strategy_version": "bogus"},
                            {**market("SHORT", "fake", anchors=None), "strategy_version": "bogus"})
        versions = {s["strategy_id"]: s["strategy_version"] for s in self.store.records("setup_observations.jsonl")}
        self.assertEqual(versions, {"trendline": TrendlineStrategy.version, "fake": "fake-v7"})

    def test_confirmation_events_carry_strategy_id_one_per_setup_per_strategy(self):
        trendline = market("LONG", state="CONFIRMING", valid=True, invalidation=2600.0)
        sr = market("LONG", "sr", anchors=None, state="CONFIRMING", valid=True, invalidation=2600.0)
        for _ in range(3):
            first_trendline, first_sr = self.store.scan(trendline, sr)
        confirmations = self.store.records("setup_confirmations.jsonl")
        self.assertEqual(sorted((c["strategy_id"], c["setup_id"]) for c in confirmations),
                         sorted([("trendline", first_trendline["setup_id"]), ("sr", first_sr["setup_id"])]))
        self.assertNotEqual(first_trendline["setup_id"], first_sr["setup_id"])

    def test_multiple_strategies_coexist_on_the_same_symbol(self):
        rounds = []
        for _ in range(4):
            rounds.append(self.store.scan(market("LONG"), market("SHORT", "sr", anchors=None, family="REVERSAL"),
                                          market("LONG", "fake", anchors=None, price=2651.0)))
        ids = {m["setup_id"] for batch in rounds for m in batch}
        self.assertEqual(len(ids), 3)  # each strategy keeps one episode across all rounds
        closing = [e for e in self.store.records("setup_lifecycle.jsonl") if e["to_state"] in {"INVALIDATED", "EXPIRED"}]
        self.assertEqual(closing, [])
        with g.isolated_store(observations, self.store.root):
            current = observations.setup_episodes("current", 50)
        self.assertEqual(sorted(e["strategy_id"] for e in current), ["fake", "sr", "trendline"])

    def test_observation_index_summarizes_the_episode_strategy(self):
        self.store.scan(market("LONG"), market("SHORT", "sr", anchors=None))
        # v4: Phase 6 shadow flag; v5: Phase 7 strategy_id/timeframe/setup_type for the Strategy Lab.
        self.assertEqual(observations._OBSERVATION_INDEX_SCHEMA, "observations-v5")
        summaries = observations._observation_index().summaries()
        self.assertEqual(sorted(s["ep"]["st"] for s in summaries if "ep" in s), ["sr", "trendline"])
        sidecar = json.loads(json.loads((self.store.root / ".index" / "setup_observations.jsonl.idx.json")
                                        .read_text(encoding="utf-8"))["body"])
        self.assertEqual(sidecar["schema"], observations._OBSERVATION_INDEX_SCHEMA)


class ScopedSuppressionTests(unittest.TestCase):
    """Closed episodes suppress only their own strategy, on both episode paths."""

    def run_case(self, full_path: bool):
        store = Store()
        try:
            if full_path:  # an irregular row forces the former full-row path for every scan
                path = store.root / "setup_observations.jsonl"
                path.write_text(json.dumps({"record_type": "setup_snapshot", "setup_id": "stp_nan", "symbol": "OTHER",
                    "direction": "LONG", "observed_at": g.BASE_NOW.isoformat(), "reference_price": math.nan}) + "\n",
                    encoding="utf-8")
            view = mock.patch.object(observations, "_FullEpisodeView", wraps=observations._FullEpisodeView)
            with view as fallback:
                # Close an sr episode (price crossed its invalidation) and a trendline episode.
                store.scan(market("LONG", "sr", anchors=None, invalidation=2640.0),
                           market("SHORT", invalidation=2660.0, price=2650.0))
                store.scan(market("LONG", "sr", anchors=None, invalidation=2640.0, price=2635.0),
                           market("SHORT", invalidation=2660.0, price=2665.0))
                self.assertEqual(len([e for e in store.records("setup_lifecycle.jsonl") if e["to_state"] == "INVALIDATED"]), 2)
                # Another strategy on the same symbol/direction: never suppressed, neither
                # by a near-price closed episode nor by one with the very same trendline.
                trendline_after_sr = store.scan(market("LONG", anchors=None, price=2636.0))[0]
                sr_after_trendline = store.scan(market("SHORT", "sr", price=2665.0, invalidation=2700.0))[0]
                # Same strategy: the existing suppression still applies.
                sr_repeat = store.scan(market("LONG", "sr", anchors=None, price=2635.5, invalidation=2600.0))[0]
                trendline_repeat = store.scan(market("SHORT", price=2665.0, invalidation=2700.0))[0]
            self.assertEqual(fallback.call_count > 0, full_path)
            closed = {e["setup_id"] for e in store.records("setup_lifecycle.jsonl") if e["to_state"] == "INVALIDATED"}
            strategy_of = {s["setup_id"]: record_strategy_id(s) for s in store.records("setup_observations.jsonl")}
            fingerprints = {s["setup_id"]: ((s.get("episode_identity") or {}).get("trendline_identity") or {}).get("fingerprint")
                            for s in store.records("setup_observations.jsonl")}
            self.assertFalse(trendline_after_sr.get("episode_suppressed"))
            self.assertFalse(sr_after_trendline.get("episode_suppressed"))
            # The sr SHORT had the exact trendline of a closed trendline SHORT episode.
            self.assertIn(fingerprints[sr_after_trendline["setup_id"]],
                          {fp for sid, fp in fingerprints.items() if sid in closed and strategy_of[sid] == "trendline"})
            for repeat, strategy_id in ((sr_repeat, "sr"), (trendline_repeat, "trendline")):
                self.assertTrue(repeat.get("episode_suppressed"))
                self.assertIn(repeat["setup_id"], closed)
                self.assertEqual(strategy_of[repeat["setup_id"]], strategy_id)
        finally:
            store.close()

    def test_indexed_path(self):
        self.run_case(full_path=False)

    def test_full_row_path(self):
        self.run_case(full_path=True)


class FailingStrategy(Strategy):
    strategy_id, version, timeframe, lifecycle = "failing", "failing-v1", "M15", "failing"

    def evaluate(self, market):
        raise RuntimeError("strategy bug")


class FakeStrategy(Strategy):
    """Always a confirmed SHORT; its rules are irrelevant, only its isolation matters."""
    strategy_id, version, timeframe, higher_timeframes, lifecycle = "fake", "fake-v1", "M15", ("H1",), "fake"

    def evaluate(self, market):
        close = float(market.rows[-1]["close"])
        return {"state": "CONFIRMING", "direction": "SHORT", "strategy_valid": True, "score": 90,
                "score_breakdown": {"fake": 90}, "setup_family": "FAKE", "entry": close,
                "stop_loss": close * 1.01, "take_profit": close * 0.98, "invalidation_hint": close * 1.01,
                "strategy_evidence": {"fake_level": close}}


class ScanLoopIsolationTests(unittest.TestCase):
    def scan(self, registry: StrategyRegistry, root: Path):
        import main
        fixtures = [{**f, "symbol": s} for f, s in zip([f for f in g.load_fixtures() if f["name"] in ("real_XAUUSD", "real_EURUSD")],
                                                       ("XAUUSD", "EURUSD"))]
        main._MT5_SESSION.update(initialized=False, initializations=0)
        try:
            with g.isolated_store(observations, root), \
                 mock.patch.object(main, "mt5", FakeMT5(fixtures)), \
                 mock.patch.object(main, "STRATEGIES", registry), \
                 mock.patch.object(main, "mt5_symbol", side_effect=lambda s: s if s in ("XAUUSD", "EURUSD") else None), \
                 mock.patch.object(main, "datetime", g.FrozenClock.make()), \
                 mock.patch.object(main, "resolve_due_market_outcomes", return_value=[]):
                markets = main.market_snapshot()
        finally:
            main._MT5_SESSION.update(initialized=False, initializations=0)
        return markets, {name: (root / name).read_bytes() for name in g.PERSISTED_FILES if (root / name).exists()}

    def test_other_strategies_never_change_the_trendline_market_or_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline, baseline_files = self.scan(g.trendline_only_registry(), Path(tmp) / "a")
            registry = StrategyRegistry()
            registry.register(FailingStrategy(), enabled=True)
            registry.register(TrendlineStrategy(), enabled=True)
            registry.register(FakeStrategy(), enabled=True)
            with self.assertLogs("trading_hub.strategies", "WARNING"):
                markets, files = self.scan(registry, Path(tmp) / "b")
        strip = lambda rows: [{k: v for k, v in m.items() if k != "strategies"} for m in rows]  # noqa: E731
        self.assertEqual(g.canonical(strip(markets)), g.canonical(strip(baseline)))
        for market_row in markets:
            entries = {entry["strategy_id"]: entry for entry in market_row["strategies"]}
            self.assertEqual(list(entries), ["failing", "trendline", "fake"])
            self.assertEqual((entries["failing"]["status"], entries["failing"]["error"]), ("ERROR", "RuntimeError"))
            self.assertEqual(entries["trendline"]["setup_id"], market_row["setup_id"])
            self.assertEqual(entries["trendline"]["state"], market_row["state"])
            self.assertEqual(entries["fake"]["direction"], "SHORT")
            self.assertNotEqual(entries["fake"]["setup_id"], market_row["setup_id"])
        self.assertEqual([m["strategies"] for m in baseline][0][0]["strategy_id"], "trendline")
        # Trendline records are unchanged; the fake strategy's records are separate and tagged.
        snapshots = [json.loads(line) for line in files["setup_observations.jsonl"].splitlines()]
        trendline_lines = [line for line in files["setup_observations.jsonl"].splitlines(keepends=True)
                           if json.loads(line)["strategy_id"] == "trendline"]
        self.assertEqual(b"".join(trendline_lines), baseline_files["setup_observations.jsonl"])
        trendline_ids = {json.loads(line)["setup_id"] for line in trendline_lines}
        trendline_events = [line for line in files["setup_lifecycle.jsonl"].splitlines(keepends=True)
                            if json.loads(line)["setup_id"] in trendline_ids]
        self.assertEqual(b"".join(trendline_events), baseline_files["setup_lifecycle.jsonl"])
        self.assertEqual(sorted({s["strategy_id"] for s in snapshots}), ["fake", "trendline"])
        fake = [s for s in snapshots if s["strategy_id"] == "fake"]
        self.assertEqual({s["strategy_version"] for s in fake}, {"fake-v1"})
        self.assertTrue(all(s["strategy_evidence"]["fake_level"] for s in fake))
        confirmations = [json.loads(line) for line in files["setup_confirmations.jsonl"].splitlines()]
        self.assertEqual(sorted(c["strategy_id"] for c in confirmations), ["fake", "fake"])
        self.assertNotIn("setup_confirmations.jsonl", baseline_files)  # trendline confirmed nothing here either


class OutcomeAndPerformanceTests(unittest.TestCase):
    def test_outcome_labels_are_unchanged_by_strategy_fields(self):
        # The golden scan rounds with verified time provenance, through both implementations.
        rounds = [[{**m, "source_timestamp": g.BASE_NOW.isoformat(), "time_provenance":
                    {"source_time_basis": "UTC", "timezone_normalization_status": "VERIFIED"}} for m in batch]
                  for batch in g.persistence_rounds()]
        results = []
        with tempfile.TemporaryDirectory() as tmp:
            for module in (observations, legacy):
                root = Path(tmp) / module.__name__
                with g.isolated_store(module, root):
                    for index, batch in enumerate(rounds):
                        g.FrozenClock.current = g.BASE_NOW + timedelta(minutes=15 * index)
                        module.record_markets(copy.deepcopy(batch))
                confirmations = [json.loads(line) for line in (root / "setup_confirmations.jsonl").read_text().splitlines()]
                snapshots = [json.loads(line) for line in (root / "setup_observations.jsonl").read_text().splitlines()]
                by_id = {s["observation_id"]: s for s in snapshots}
                reference = {s["symbol"]: float(s["reference_price"]) for s in snapshots}
                base = g.BASE_NOW.timestamp() + 3600
                bars = {symbol: [{"time": base + i * 900, "open": price, "close": price,
                                  "high": price * (1 + 0.0015 * (i % 23)), "low": price * (1 - 0.0015 * (i % 19))}
                                 for i in range(200)] for symbol, price in reference.items()}
                watch = [s for s in snapshots if not s["rule_evidence"].get("strategy_valid")]
                outcomes = resolve_due_market_outcomes(confirmations, by_id, bars, [], ("1h", "4h", "24h"),
                                                       now=g.BASE_NOW + timedelta(days=3), watch_snapshots=watch)
                results.append([{k: v for k, v in o.items() if k != "outcome_id"} for o in outcomes])
        labels = {o.get("label") for o in results[0]}
        self.assertGreater(len(results[0]), 10)
        self.assertTrue(labels & {"WIN", "LOSS"}, labels)
        self.assertEqual(results[0], results[1])
        self.assertTrue(all("strategy_id" not in o for o in results[0]))

    def test_performance_groups_by_strategy_without_mixing(self):
        events, outcomes = [], []
        plan = [(None, "WIN"), (None, "LOSS"), ("trendline", "WIN"), ("sr", "LOSS"), ("sr", "LOSS"), ("fake", None)]
        for index, (strategy_id, label) in enumerate(plan):
            event = {"setup_id": f"stp_{index}", "observation_id": f"obs_{index}", "symbol": "XAUUSD",
                     "confirmed_at": f"2026-09-23T0{index}:00:00+00:00", "setup_type": "REVERSAL", "timeframe": "M15"}
            if strategy_id:
                event["strategy_id"] = strategy_id
            events.append(event)
            if label:
                outcomes.append({"record_type": "market_outcome", "setup_id": f"stp_{index}",
                                 "observation_id": f"obs_{index}", "horizon": "4h", "label": label})
        for days in (1, 3):
            report = performance_report(events, outcomes, [], report_date="2026-09-23", days=days,
                                        timezone_name="UTC")
            groups = report["summary"]["by_strategy"]
            with self.subTest(days=days):
                self.assertEqual(set(groups), {"trendline", "sr", "fake"})
                self.assertEqual((groups["trendline"]["win"], groups["trendline"]["loss"]), (2, 1))  # 2 legacy + 1 tagged
                self.assertEqual((groups["sr"]["win"], groups["sr"]["loss"]), (0, 2))
                self.assertEqual(groups["fake"]["pending"], 1)
                self.assertEqual(sum(sum(g_.values()) for g_ in groups.values()), len(events))
        day = performance_report(events, outcomes, [], report_date="2026-09-23", timezone_name="UTC")["daily"][0]
        self.assertEqual([s["strategy_id"] for s in day["setups"]], ["trendline", "trendline", "trendline", "sr", "sr", "fake"])


if __name__ == "__main__":
    unittest.main()
