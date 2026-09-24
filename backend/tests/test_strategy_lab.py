"""Phase 7: Strategy Lab measurement, outcome grouping and ML dataset separation.

Setups are recorded through the real record_markets; outcomes come from the real
outcome resolver (verified provenance) plus a legacy-style unverified record.
Nothing is counted as a target or stop hit unless it passes the ML dataset's
integrity rules, and strategies are never combined.
"""
from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g  # noqa: E402
import sr_fixtures as f  # noqa: E402

import main  # noqa: E402
import ml_dataset  # noqa: E402
import observations  # noqa: E402
import strategy_lab  # noqa: E402
from outcomes import resolve_due_market_outcomes  # noqa: E402
from test_strategy_isolation import IsolationTestCase, market  # noqa: E402
from test_support_resistance import evaluate, sr_market  # noqa: E402


def rising_bars(start: float, step: float, count: int = 40) -> list[dict]:
    base = g.BASE_NOW.timestamp() + 60
    return [{"time": base + i * 900, "open": start + step * i, "high": start + step * i + 0.3,
             "low": start + step * i - 0.3, "close": start + step * i} for i in range(count)]


class StrategyLabTests(IsolationTestCase):
    def setUp(self):
        super().setUp()
        # Trendline: one confirmed setup (unverified time provenance, as in live data today).
        # S/R shadow: a confirmed LONG (XAUUSD), a confirmed SHORT (EURUSD), a developing LONG (GBPUSD).
        self.sr_long = evaluate(f.support_ending("bounce"))
        self.sr_short = evaluate(f.resistance_rejection())
        batch = self.store.scan(market("LONG", state="CONFIRMING", valid=True, invalidation=2600.0),
                                sr_market(self.sr_long, "XAUUSD"), sr_market(self.sr_short, "EURUSD"),
                                sr_market(evaluate(f.support_ending("no_rejection")), "GBPUSD"))
        self.trend_id, self.sr_long_id, self.sr_short_id, self.sr_dev_id = (m["setup_id"] for m in batch)
        confirmations = self.store.records("setup_confirmations.jsonl")
        snapshots = {s["observation_id"]: s for s in self.store.records("setup_observations.jsonl")}
        bars = {"XAUUSD": rising_bars(101.6, 0.8), "EURUSD": rising_bars(108.4, 0.8), "SYN": rising_bars(2650.0, 1.0)}
        self.resolved = resolve_due_market_outcomes(confirmations, snapshots, bars, [], ("1h", "4h", "24h"),
                                                    now=g.BASE_NOW + timedelta(days=2))
        trend_confirmation = next(c for c in confirmations if c["setup_id"] == self.trend_id)
        # A legacy-style WIN without integrity proof: must be counted as unverified, never as a target hit.
        self.unverified = {"record_type": "market_outcome", "setup_id": self.trend_id,
                           "observation_id": trend_confirmation["observation_id"], "horizon": "4h", "label": "WIN"}
        self.outcomes = [*self.resolved, self.unverified]

    def report(self, **kwargs):
        with g.isolated_store(observations, self.store.root):
            return {item["strategy_id"]: item for item in strategy_lab.strategy_lab_report(self.outcomes, **kwargs)["strategies"]}

    def test_counts_are_per_strategy_and_never_mixed(self):
        report = self.report()
        self.assertEqual(list(report), ["trendline", "support_resistance"])
        sr, trend = report["support_resistance"], report["trendline"]
        self.assertEqual((sr["mode"], sr["version"], trend["mode"]), ("SHADOW", "sr-levels-v1", "LIVE"))
        self.assertEqual((sr["setups"]["total"], trend["setups"]["total"]), (3, 1))
        self.assertEqual((sr["setups"]["by_state"]["CONFIRMED"], sr["setups"]["by_state"]["DEVELOPING"]), (2, 1))
        self.assertEqual((sr["confirmations"], trend["confirmations"]), (2, 1))
        self.assertEqual((sr["shadow_records"], trend["shadow_records"]), (3, 0))
        self.assertEqual(set(sr["by_instrument"]), {"XAUUSD", "EURUSD", "GBPUSD"})
        self.assertEqual(set(trend["by_instrument"]), {"XAUUSD"})
        self.assertEqual({k: v["setups"] for k, v in sr["by_direction"].items()}, {"LONG": 2, "SHORT": 1})
        self.assertEqual({k: v["setups"] for k, v in sr["by_timeframe"].items()}, {"M15": 3})
        self.assertEqual({k: v["setups"] for k, v in sr["by_setup_type"].items()}, {"SR_BOUNCE": 3})
        self.assertTrue(all(row["shadow"] for row in sr["recent"]))
        self.assertEqual({row["setup_id"] for row in sr["recent"]}, {self.sr_long_id, self.sr_short_id, self.sr_dev_id})

    def test_verified_outcomes_are_grouped_by_strategy_and_unverified_never_count(self):
        report = self.report()
        sr, trend = report["support_resistance"], report["trendline"]
        self.assertEqual({k: sr["outcomes"][k] for k in strategy_lab.OUTCOME_KINDS},
                         {"pending": 0, "unverified": 0, "verified_target": 1, "verified_stop": 1, "verified_other": 0})
        self.assertEqual({k: trend["outcomes"][k] for k in strategy_lab.OUTCOME_KINDS},
                         {"pending": 0, "unverified": 1, "verified_target": 0, "verified_stop": 0, "verified_other": 0})
        self.assertEqual((sr["by_instrument"]["XAUUSD"]["verified_target"], sr["by_instrument"]["EURUSD"]["verified_stop"]), (1, 1))
        recent = {row["setup_id"]: row for row in sr["recent"]}
        self.assertEqual((recent[self.sr_long_id]["outcome"], recent[self.sr_short_id]["outcome"], recent[self.sr_dev_id]["outcome"]),
                         ("verified_target", "verified_stop", None))
        # Without the unverified record the trendline setup is pending, still never a win.
        self.outcomes = list(self.resolved)
        self.assertEqual(self.report()["trendline"]["outcomes"]["pending"], 1)

    def test_win_rate_only_with_enough_verified_outcomes(self):
        report = self.report()
        self.assertIsNone(report["support_resistance"]["win_rate"])
        self.assertIn("needs 30", report["support_resistance"]["win_rate_note"])
        self.assertEqual(self.report(min_verified_for_rate=2)["support_resistance"]["win_rate"], 50.0)
        self.assertIsNone(self.report(min_verified_for_rate=2)["trendline"]["win_rate"], "an unverified WIN is no sample")

    def test_classification_uses_the_first_barrier_and_verification(self):
        confirmation = {"observation_id": "o1"}
        snapshot = {"observation_id": "o1"}
        self.assertEqual(strategy_lab.classify_outcome(confirmation, [], snapshot), ("pending", None))
        self.assertEqual(strategy_lab.classify_outcome(confirmation, [{"observation_id": "o1", "horizon": "1h", "label": "LOSS"}], snapshot),
                         ("unverified", None))
        verified = [o for o in self.resolved if o["setup_id"] == self.sr_long_id]
        conf = next(c for c in self.store.records("setup_confirmations.jsonl") if c["setup_id"] == self.sr_long_id)
        snap = next(s for s in self.store.records("setup_observations.jsonl") if s["observation_id"] == conf["observation_id"])
        kind, horizon = strategy_lab.classify_outcome(conf, verified, snap)
        self.assertEqual(kind, "verified_target")
        self.assertEqual(horizon, min((o["horizon"] for o in verified if o["label"] == "WIN"), key=["15m", "1h", "4h", "24h"].index))

    def test_api_route_and_setup_evidence(self):
        with g.isolated_store(observations, self.store.root), mock.patch.object(main, "list_records", return_value=self.outcomes):
            response = main.strategy_lab(recent=25)
            detail = main.setup_detail(self.sr_long_id)
            garden = main.setup_episode_feed(bucket="all", limit=100)
        self.assertEqual([s["strategy_id"] for s in response["strategies"]], ["trendline", "support_resistance"])
        evidence = detail["snapshots"][-1]["strategy_evidence"]
        self.assertEqual(evidence["level"]["type"], "SUPPORT")
        self.assertTrue(evidence["confirmation"]["passed"])
        self.assertEqual(evidence["plan"]["rr"], self.sr_long["rr"])
        self.assertEqual({r["strategy_id"] for b in ("current", "confirmed", "closed") for r in garden[b]}, {"trendline"},
                         "measuring S/R never puts it in the Garden")


class MlDatasetSeparationTests(IsolationTestCase):
    def test_audit_separates_strategies_and_never_mixes_them(self):
        self.store.scan(market("LONG", state="CONFIRMING", valid=True, invalidation=2600.0), sr_market(evaluate(f.support_ending("bounce"))))
        rows = {name: self.store.records(name) for name in g.PERSISTED_FILES}
        legacy_row = {"symbol": "EURUSD", "direction": "SHORT", "state": "DEVELOPING", "price": 1.17, "timestamp": g.BASE_NOW.isoformat()}
        legacy_event = {"setup_id": "stp_legacy_abc", "to_state": "EXPIRED"}
        stray_outcome = {"record_type": "market_outcome", "setup_id": "stp_unknown", "observation_id": "obs_unknown", "horizon": "4h", "label": "WIN"}
        split = ml_dataset.split_by_strategy(rows["setup_observations.jsonl"] + [legacy_row], [stray_outcome],
                                             rows["setup_lifecycle.jsonl"] + [legacy_event], rows["setup_confirmations.jsonl"])
        self.assertEqual(set(split), {"trendline", "support_resistance", "UNATTRIBUTED"})
        self.assertEqual(len(split["support_resistance"]["observations"]), 1)
        self.assertTrue(all(r.get("shadow") is True for r in split["support_resistance"]["observations"]))
        self.assertIn(legacy_row, split["trendline"]["observations"])
        self.assertIn(legacy_event, split["trendline"]["lifecycle_events"])
        self.assertEqual(split["UNATTRIBUTED"]["market_outcomes"], [stray_outcome])
        self.assertEqual([c["strategy_id"] for c in split["support_resistance"]["confirmation_events"]], ["support_resistance"])
        audit = ml_dataset.audit_by_strategy(rows["setup_observations.jsonl"], [], rows["setup_lifecycle.jsonl"], rows["setup_confirmations.jsonl"])
        self.assertEqual({k: (v["mode"], v["records"]["observations"], v["shadow_snapshots"]) for k, v in audit.items()},
                         {"trendline": ("LIVE", 1, 0), "support_resistance": ("SHADOW", 1, 1)})
        self.assertIn("statistics", audit["support_resistance"])

    def test_live_audit_labels_its_scope(self):
        with mock.patch.object(ml_dataset, "prepare_dataset", wraps=ml_dataset.prepare_dataset):
            with mock.patch.multiple(ml_dataset, LOG_FILE=self.store.root / "setup_observations.jsonl",
                                     LIFECYCLE_FILE=self.store.root / "setup_lifecycle.jsonl",
                                     CONFIRMATIONS_FILE=self.store.root / "setup_confirmations.jsonl",
                                     MARKET_OUTCOMES_FILE=self.store.root / "market_outcomes.jsonl",
                                     TRADE_OUTCOMES_FILE=self.store.root / "trade_outcomes.jsonl"):
                self.store.scan(market("LONG"), sr_market(evaluate(f.support_ending("bounce"))))
                audit = ml_dataset.audit_live_dataset()
        self.assertEqual(audit["strategy_scope"], "ALL_STRATEGIES_COMBINED")
        self.assertEqual(set(audit["by_strategy"]), {"trendline", "support_resistance"})
        self.assertEqual(audit["by_strategy"]["support_resistance"]["shadow_snapshots"], 1)


if __name__ == "__main__":
    unittest.main()
