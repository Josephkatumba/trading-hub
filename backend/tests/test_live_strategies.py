"""Phase 10b: Trendline, Support & Resistance and Trend / Momentum are all LIVE.

LIVE means: evaluated on live data, persisted without the research flag, visible in the
live episode views (Garden), confirmed setups reach the live confirmation list that
drives notifications, and outcomes are tracked. It is not a claim of profitability.
Each strategy stays independent (scoped by strategy_id); promoting a strategy changes
only its mode, never its calculations, and never rewrites historical records.
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
import sr_fixtures as srf  # noqa: E402
import tm_fixtures as tmf  # noqa: E402

import main  # noqa: E402
import observations  # noqa: E402
import strategies  # noqa: E402
import strategy_lab  # noqa: E402
from outcomes import resolve_due_market_outcomes  # noqa: E402
from performance import performance_report  # noqa: E402
from test_market_data import IC_MARKETS, FakeBroker, run_scan  # noqa: E402
from test_strategy_isolation import IsolationTestCase, Store, market  # noqa: E402
from test_support_resistance import evaluate as sr_evaluate, sr_market  # noqa: E402
from test_trend_momentum import ScenarioBroker, evaluate as tm_evaluate, tm_market  # noqa: E402

LIVE_IDS = ["trendline", "support_resistance", "trend_momentum"]


def ids(rows):
    return {row["strategy_id"] for row in rows}


class RegistryTests(unittest.TestCase):
    def test_three_live_strategies_and_nothing_else_registered(self):
        self.assertEqual(strategies.REGISTRY.registered(), LIVE_IDS)
        self.assertEqual(strategies.REGISTRY.live(), LIVE_IDS)
        for name in ("smc", "crt", "ict"):
            with self.assertRaises(KeyError):
                strategies.REGISTRY.mode(name)                  # not implemented: never evaluated, never shown
        with self.assertRaises(ValueError):
            strategies.StrategyRegistry().register(strategies.TrendMomentumStrategy(), mode="RESEARCH")   # modes: LIVE / SHADOW
        self.assertEqual([(d["strategy_id"], d["version"]) for d in strategies.REGISTRY.describe()],
                         [("trendline", "trendline-first-v4"), ("support_resistance", "sr-levels-v1"), ("trend_momentum", "tm-pullback-v1")])


class LivePersistenceTests(IsolationTestCase):
    def scan_all(self):
        return self.store.scan(market("LONG", state="CONFIRMING", valid=True, invalidation=2600.0),
                               sr_market(sr_evaluate(srf.support_ending("bounce"))),
                               tm_market(tm_evaluate(), verified=True))

    def test_every_live_strategy_persists_live_records_and_confirmations(self):
        batch = self.scan_all()
        snapshots = self.store.records("setup_observations.jsonl")
        self.assertEqual([s["strategy_id"] for s in snapshots], LIVE_IDS)
        self.assertFalse(any("shadow" in s for s in snapshots))
        self.assertEqual(len({m["setup_id"] for m in batch}), 3, "three independent episodes on XAUUSD")
        confirmations = self.store.records("setup_confirmations.jsonl")
        self.assertEqual(sorted((c["strategy_id"], c["symbol"], c["direction"]) for c in confirmations),
                         [("support_resistance", "XAUUSD", "LONG"), ("trend_momentum", "XAUUSD", "LONG"), ("trendline", "XAUUSD", "LONG")])
        self.assertFalse(any("shadow" in c for c in confirmations))
        for confirmation in confirmations:                     # what a notification shows is on the record
            for key in ("strategy_id", "strategy_version", "symbol", "direction", "setup_type", "score", "confirmed_at", "rule_evidence"):
                self.assertIsNotNone(confirmation.get(key), (confirmation["strategy_id"], key))

    def test_live_views_and_notifications_include_all_three(self):
        self.scan_all()
        confirmations = self.store.records("setup_confirmations.jsonl")
        with g.isolated_store(observations, self.store.root):
            episodes = observations.setup_episodes("all", 100)
            api = main.setup_episode_feed(bucket="all", limit=100)
            snapshots = observations.performance_observations()
        self.assertEqual(ids(episodes), set(LIVE_IDS))
        self.assertEqual({r["strategy_id"] for b in ("current", "confirmed", "closed") for r in api[b]}, set(LIVE_IDS))
        self.assertEqual(len(api["confirmed"]), 3, "each strategy's episode once")
        report = performance_report(confirmations, [], snapshots, report_date=g.BASE_NOW.date().isoformat(), timezone_name="UTC")
        day = report["daily"][0]
        # The live setups list drives confirmation notifications.
        self.assertEqual(sorted(s["strategy_id"] for s in day["setups"]), sorted(LIVE_IDS))
        self.assertEqual(day["shadow_strategies"], [])
        self.assertEqual(set(day["by_strategy"]), set(LIVE_IDS))

    def test_outcomes_are_tracked_per_strategy(self):
        batch = self.scan_all()
        confirmations = self.store.records("setup_confirmations.jsonl")
        snapshots = {s["observation_id"]: s for s in self.store.records("setup_observations.jsonl")}
        # Verified provenance only for S/R and trend/momentum (sr_market / tm_market): a falling path.
        base = g.BASE_NOW.timestamp() + 60
        falling = [{"time": base + i * 900, "open": 101.0 - 0.8 * i, "high": 101.3 - 0.8 * i, "low": 100.7 - 0.8 * i,
                    "close": 101.0 - 0.8 * i} for i in range(40)]
        outcomes = resolve_due_market_outcomes(confirmations, snapshots, {"XAUUSD": falling}, [], ("1h", "4h", "24h"),
                                               now=g.BASE_NOW + timedelta(days=2))
        self.assertTrue(outcomes)
        self.assertLessEqual({o["setup_id"] for o in outcomes}, {m["setup_id"] for m in batch})
        with g.isolated_store(observations, self.store.root):
            report = {item["strategy_id"]: item for item in strategy_lab.strategy_lab_report(outcomes)["strategies"]}
        for strategy_id in LIVE_IDS:
            self.assertEqual((report[strategy_id]["mode"], report[strategy_id]["confirmations"]), ("LIVE", 1), strategy_id)
            self.assertIsNone(report[strategy_id]["win_rate"], "the minimum verified sample still applies")
        for strategy_id, item in report.items():
            counted = sum(item["outcomes"][k] for k in strategy_lab.OUTCOME_KINDS)
            self.assertEqual(counted, item["confirmations"], strategy_id)
        # Verified provenance (S/R, Trend/Momentum): stop hit first on the falling path, each counted
        # under its own strategy; the trendline record has unverified time provenance: pending.
        self.assertEqual(report["support_resistance"]["outcomes"]["verified_stop"], 1)
        self.assertEqual(report["trend_momentum"]["outcomes"]["verified_stop"], 1)
        self.assertEqual(report["trendline"]["outcomes"]["pending"], 1)

    def test_one_strategy_never_invalidates_or_suppresses_another(self):
        sr_short = sr_evaluate(srf.resistance_rejection())
        tm_short = tm_evaluate(bearish=True)
        rounds = [self.store.scan(market("LONG", price=2650.0, invalidation=2600.0), sr_market(sr_short), tm_market(tm_short))
                  for _ in range(3)]
        episodes = {tuple(m["setup_id"] for m in batch) for batch in rounds}
        self.assertEqual(len(episodes), 1, "every episode continues")
        for setup_id in next(iter(episodes)):
            self.assertFalse([e for e in self.store.events_for(setup_id) if e["to_state"] in ("INVALIDATED", "EXPIRED")])
        # Trend/Momentum's own invalidation closes only its episode; the others continue unsuppressed.
        trend_id, sr_id, tm_id = next(iter(episodes))
        after = self.store.scan(market("LONG", price=2650.0, invalidation=2600.0), sr_market(sr_short),
                                tm_market(tm_short, price=tm_short["stop_loss"] + 0.01))
        self.assertEqual(self.store.events_for(tm_id)[-1]["to_state"], "INVALIDATED")
        self.assertEqual((after[0]["setup_id"], after[1]["setup_id"]), (trend_id, sr_id))
        self.assertFalse(after[0].get("episode_suppressed") or after[1].get("episode_suppressed"))


class HistoricalRecordTests(unittest.TestCase):
    def test_research_records_keep_their_flag_and_live_records_follow(self):
        store = Store()
        try:
            with g.research_mode(observations):                       # written while S/R and TM were research
                old = store.scan(sr_market(sr_evaluate(srf.support_ending("bounce")), "EURUSD"), tm_market(tm_evaluate(), "GBPUSD"))
            before = (store.root / "setup_observations.jsonl").read_bytes()
            new = store.scan(sr_market(sr_evaluate(srf.support_ending("bounce")), "USDJPY"), tm_market(tm_evaluate(), "AUDUSD"))
            after = (store.root / "setup_observations.jsonl").read_bytes()
            self.assertEqual(after[:len(before)], before, "historical records are never rewritten")
            rows = [json.loads(line) for line in after.splitlines()]
            self.assertEqual([(r["strategy_id"], r["symbol"], r.get("shadow")) for r in rows],
                             [("support_resistance", "EURUSD", True), ("trend_momentum", "GBPUSD", True),
                              ("support_resistance", "USDJPY", None), ("trend_momentum", "AUDUSD", None)])
            with g.isolated_store(observations, store.root):
                live = observations.setup_episodes("all", 100)
                review = observations.setup_episodes("all", 100, include_shadow=True)
            self.assertEqual({r["setup_id"] for r in live}, {m["setup_id"] for m in new})
            self.assertEqual({r["setup_id"]: r["strategy_id"] for r in review if r["setup_id"] in {m["setup_id"] for m in old}},
                             {old[0]["setup_id"]: "support_resistance", old[1]["setup_id"]: "trend_momentum"})
        finally:
            store.close()


class ScanLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.trendline_only = run_scan(FakeBroker(IC_MARKETS), g.trendline_only_registry(), root=root / "a")
        cls.live = run_scan(FakeBroker(IC_MARKETS), strategies.build_default_registry(), root=root / "b")
        with g.research_mode(observations) as research:
            cls.research = run_scan(FakeBroker(IC_MARKETS), research, root=root / "c")
        scenarios = {"XAUUSD": {}, "EURUSD": {"bearish": True}}
        broker = lambda: ScenarioBroker({s: tmf.scenario(symbol=s, **kw) for s, kw in scenarios.items()})  # noqa: E731
        cls.tm_live = run_scan(broker(), strategies.build_default_registry(), watchlist=list(scenarios), root=root / "d")
        with g.research_mode(observations) as research:
            cls.tm_research = run_scan(broker(), research, watchlist=list(scenarios), root=root / "e")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @staticmethod
    def records(files, name="setup_observations.jsonl"):
        return [json.loads(line) for line in files.get(name, b"").splitlines()]

    def test_trendline_markets_and_records_stay_byte_identical(self):
        (base, base_files), (markets, files) = self.trendline_only, self.live
        strip = lambda rows: [{k: v for k, v in m.items() if k != "strategies"} for m in rows]  # noqa: E731
        self.assertEqual(g.canonical(strip(markets)), g.canonical(strip(base)))
        lines = files["setup_observations.jsonl"].splitlines(keepends=True)
        trend = [line for line in lines if json.loads(line)["strategy_id"] == "trendline"]
        self.assertEqual(b"".join(trend), base_files["setup_observations.jsonl"])
        for row in markets:
            self.assertEqual([(e["strategy_id"], e["mode"]) for e in row["strategies"]], [(s, "LIVE") for s in LIVE_IDS])

    def test_promotion_changes_the_mode_only_never_the_calculations(self):
        # Same scans with S/R and Trend/Momentum LIVE vs SHADOW: identical strategy results and records,
        # apart from the mode and the research flag.
        for (live, live_files), (research, research_files) in ((self.live, self.research), (self.tm_live, self.tm_research)):
            for a, b in zip(live, research):
                for x, y in zip(a["strategies"], b["strategies"]):
                    self.assertEqual({k: v for k, v in x.items() if k != "mode"}, {k: v for k, v in y.items() if k != "mode"})
            for name in g.PERSISTED_FILES:
                strip = lambda rows: [{k: v for k, v in r.items() if k != "shadow"} for r in rows]  # noqa: E731
                self.assertEqual(strip(self.records(live_files, name)), strip(self.records(research_files, name)), name)
        tm_rows = [r for r in self.records(self.tm_live[1]) if r["strategy_id"] == "trend_momentum"]
        self.assertTrue(tm_rows and not any("shadow" in r for r in tm_rows))
        self.assertTrue([c for c in self.records(self.tm_live[1], "setup_confirmations.jsonl") if c["strategy_id"] == "trend_momentum"])


if __name__ == "__main__":
    unittest.main()
