"""Phase 11: Trend / Momentum v2 stop model, confirmed-event lifecycle, A/B replay and the
historical evaluation layer.

Stop levels are recomputed here from the fixture bars with literal parameters, never
copied from the strategy's output. Lifecycle tests go through the real record_markets.
Evaluation tests use the real outcome resolver and integrity rules.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
import unittest.mock
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g  # noqa: E402
import tm_fixtures as f  # noqa: E402

import analyst  # noqa: E402
import evaluation  # noqa: E402
import observations  # noqa: E402
import stop_ab  # noqa: E402
from episode_identity import CONFIRMED_EVENTS_LIFECYCLE, LEVEL_EPISODES_LIFECYCLE, MATCHER_VERSION  # noqa: E402
from outcomes import resolve_due_market_outcomes  # noqa: E402
from strategies import (REGISTRY, LegacyTrendMomentumStrategy, MarketInput, SupportResistanceStrategy,  # noqa: E402
                        TrendlineStrategy, TrendMomentumStrategy)
from strategies import trend_momentum as tm  # noqa: E402
from test_strategy_isolation import IsolationTestCase, market  # noqa: E402
from test_trend_momentum import closed, h1_structure, tm_market  # noqa: E402

V2, V1 = TrendMomentumStrategy(), LegacyTrendMomentumStrategy()


def with_bars(scenario: MarketInput, **frames) -> MarketInput:
    bars = {**scenario.bars, **frames}
    return MarketInput(scenario.symbol, bars["M15"], higher_rows=bars["H1"], bars=bars)


def forming_close(scenario: MarketInput, price: float) -> MarketInput:
    m15 = [dict(bar) for bar in scenario.bars["M15"]]
    m15[-1].update(close=price, high=max(m15[-1]["high"], price), low=min(m15[-1]["low"], price))
    return with_bars(scenario, M15=m15)


def expected_stop(scenario: MarketInput, long: bool = True) -> tuple[float, float, float, float]:
    frames = scenario.bars
    _, _, pullback = h1_structure(frames, long)
    unit, unit_m15 = tm.atr(closed(frames, "H1")), tm.atr(closed(frames, "M15"))
    buffer = min(max(1.0 * unit_m15, 0.25 * unit), 0.5 * unit)
    return (pullback - buffer if long else pullback + buffer), pullback, unit, buffer


# ------------------------------------------------------------------------------- stop model
class StopModelTests(unittest.TestCase):
    def test_structural_stop_beyond_the_pullback_extreme_with_the_atr_buffer(self):
        for bearish in (False, True):
            scenario = f.scenario(bearish=bearish)
            result = V2.evaluate(scenario)
            stop, pullback, unit, buffer = expected_stop(scenario, long=not bearish)
            evidence = result["strategy_evidence"]["stop"]
            with self.subTest(bearish=bearish):
                self.assertAlmostEqual(result["stop_loss"], stop, places=9)
                self.assertEqual(evidence["structural_invalidation"], pullback)
                self.assertAlmostEqual(evidence["buffer"], buffer, places=9)
                self.assertEqual((evidence["basis"], evidence["model"]), ("STRUCTURAL", "structure-atr-guard-v2"))
                # never on the structure itself: strictly beyond it
                self.assertLess(result["stop_loss"], pullback) if not bearish else self.assertGreater(result["stop_loss"], pullback)

    def test_buffer_is_clamped_between_quarter_and_half_an_h1_atr(self):
        unit = 10.0
        self.assertEqual(tm.stop_buffer(tm.STRATEGY_VERSION, unit, 1.0), 2.5)        # quiet M15: floor 0.25 ATR(H1)
        self.assertEqual(tm.stop_buffer(tm.STRATEGY_VERSION, unit, 4.0), 4.0)        # one ATR(M15)
        self.assertEqual(tm.stop_buffer(tm.STRATEGY_VERSION, unit, 9.0), 5.0)        # volatile M15: cap 0.5 ATR(H1)
        self.assertEqual(tm.stop_buffer(tm.LEGACY_VERSION, unit, 9.0), 2.5)          # v1: fixed 0.25 ATR(H1)

    def test_entry_stop_target_and_rr_are_consistent(self):
        for bearish in (False, True):
            result = V2.evaluate(f.scenario(bearish=bearish))
            entry, stop, target = result["entry"], result["stop_loss"], result["take_profit"]
            with self.subTest(bearish=bearish):
                if bearish:
                    self.assertTrue(target < entry < stop)
                else:
                    self.assertTrue(stop < entry < target)
                self.assertEqual(result["invalidation_hint"], stop)
                self.assertEqual(result["rr"], round(abs(target - entry) / abs(entry - stop), 2))
                evidence = result["strategy_evidence"]["stop"]
                self.assertEqual((evidence["entry"], evidence["stop"], evidence["target"], evidence["rr"]), (entry, stop, target, result["rr"]))
                self.assertAlmostEqual(evidence["stop_distance"], abs(entry - stop), places=9)

    def test_oversized_structural_risk_is_rejected_not_forced(self):
        scenario = f.scenario()
        base = V2.evaluate(scenario)
        unit = base["strategy_evidence"]["atr"]["H1"]
        risk = base["risk_distance"]
        # Shrink the envelope below this structure's risk: the same stop must now be rejected.
        with unittest.mock.patch.object(tm, "MAX_RISK_ATR", (risk / unit) * 0.9):
            rejected = V2.evaluate(scenario)
        self.assertEqual(rejected["state"], "CONFIRMING")
        self.assertFalse(rejected["strategy_valid"])
        self.assertEqual(rejected["stop_loss"], base["stop_loss"], "the stop is never moved to force a trade")
        stop = rejected["strategy_evidence"]["stop"]
        self.assertEqual(stop["risk_quality"], "RISK_REJECTED")
        self.assertIn("Structural invalidation requires excessive risk", stop["rejection_reason"])
        self.assertIn("Setup rejected.", rejected["reason"])
        self.assertIn("stop_ok", rejected["strategy_evidence"]["confirmation"]["failed"])

    def test_genuinely_wide_structure_fixture_is_rejected(self):
        result = V2.evaluate(f.scenario(impulse_step=0.1))
        stop = result["strategy_evidence"]["stop"]
        self.assertFalse(result["strategy_valid"])
        self.assertEqual(stop["risk_quality"], "RISK_REJECTED")
        self.assertGreater(stop["stop_distance"], stop["max_stop_distance"])

    def test_a_1_to_79_style_plan_is_never_confirmed(self):
        # Price has run back almost to structural invalidation: tiny risk, huge R:R.
        scenario = f.scenario()
        stop, _, unit, _ = expected_stop(scenario)
        near = forming_close(scenario, stop + 0.1 * unit)
        result = V2.evaluate(near)
        self.assertGreater(result["rr"], 10)
        self.assertFalse(result["strategy_valid"])
        self.assertAlmostEqual(result["stop_loss"], stop, places=9, msg="the stop does not follow price")
        self.assertEqual(result["strategy_evidence"]["stop"]["risk_quality"], "STOP_TOO_TIGHT")
        self.assertIn("inside normal noise", result["reason"])

    def test_risk_quality_labels(self):
        self.assertEqual(tm.risk_quality(0.3, 1.0), "STOP_TOO_TIGHT")
        self.assertEqual(tm.risk_quality(1.2, 1.0), "NORMAL_RISK")
        self.assertEqual(tm.risk_quality(2.5, 1.0), "WIDE_STRUCTURE")
        self.assertEqual(tm.risk_quality(3.1, 1.0), "RISK_REJECTED")
        self.assertEqual(tm.risk_quality(0.0, 1.0), "INVALID")

    def test_closed_bar_inputs_only(self):
        scenario = f.scenario()
        base = V2.evaluate(scenario)
        frames = copy.deepcopy(dict(scenario.bars))
        for tf in ("H1", "H4", "D1"):                               # forming higher-timeframe bars: anything
            frames[tf][-1].update(high=frames[tf][-1]["high"] * 3, low=frames[tf][-1]["low"] / 3, close=frames[tf][-1]["close"] * 2)
        frames["M15"][-1].update(high=frames["M15"][-1]["high"] * 3, low=frames["M15"][-1]["low"] / 3)  # forming M15 range
        changed = V2.evaluate(with_bars(scenario, **frames))
        self.assertEqual(json.dumps(changed, sort_keys=True), json.dumps(base, sort_keys=True))

    def test_no_lookahead_future_bars_are_not_an_input(self):
        scenario = f.scenario()
        base = V2.evaluate(scenario)
        m15 = list(scenario.bars["M15"])
        future = dict(m15[-1], time=m15[-1]["time"] + 900, high=m15[-1]["high"] + 50, low=m15[-1]["low"] - 50)
        # The replay feeds only bars that had opened; a bar after the forming one would be a later scan.
        market = stop_ab.market_at("TEST", {**scenario.bars, "M15": m15 + [future]},
                                   {tf: [b["time"] for b in rows] for tf, rows in {**scenario.bars, "M15": m15 + [future]}.items()},
                                   len(m15) - 1)
        self.assertEqual(market.bars["M15"][-1]["high"], m15[-1]["open"], "the forming bar is flat at its open")
        self.assertNotIn(future["time"], [b["time"] for b in market.bars["M15"]])
        self.assertEqual(base["stop_loss"], V2.evaluate(scenario)["stop_loss"])

    def test_deterministic(self):
        for kwargs in ({}, {"bearish": True}, {"trigger": False}, {"impulse_step": 0.1}):
            first, second = V2.evaluate(f.scenario(**kwargs)), V2.evaluate(f.scenario(**kwargs))
            self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True), kwargs)

    def test_setup_rules_are_identical_in_both_versions(self):
        for kwargs in ({}, {"bearish": True}, {"trigger": False}, {"choppy": True}, {"retracement": 0.3}, {"d1_trend": -0.3}):
            a, b = V1.evaluate(f.scenario(**kwargs)), V2.evaluate(f.scenario(**kwargs))
            with self.subTest(**kwargs):
                self.assertEqual((a["state"], a["direction"], a["take_profit"], a["score_breakdown"].get("h4_trend")),
                                 (b["state"], b["direction"], b["take_profit"], b["score_breakdown"].get("h4_trend")))


class VersioningTests(unittest.TestCase):
    def test_new_version_registered_old_version_reproducible(self):
        self.assertEqual(REGISTRY.get("trend_momentum").version, "tm-pullback-v2")
        self.assertEqual(V2.evaluate(f.scenario())["strategy_version"], "tm-pullback-v2")
        v1 = V1.evaluate(f.scenario())
        self.assertEqual(v1["strategy_version"], "tm-pullback-v1")
        frames = f.scenario().bars
        _, _, pullback = h1_structure(frames, True)
        self.assertAlmostEqual(v1["stop_loss"], pullback - 0.25 * tm.atr(closed(frames, "H1")), places=9)
        self.assertNotIn("stop", v1["strategy_evidence"], "v1 records keep their v1 evidence shape")

    def test_lifecycle_policies(self):
        self.assertEqual(TrendMomentumStrategy.lifecycle, CONFIRMED_EVENTS_LIFECYCLE)
        self.assertEqual(LegacyTrendMomentumStrategy.lifecycle, MATCHER_VERSION)
        self.assertEqual(TrendlineStrategy.lifecycle, MATCHER_VERSION, "trendline lifecycle unchanged")
        self.assertEqual(SupportResistanceStrategy.lifecycle, LEVEL_EPISODES_LIFECYCLE, "S/R: level episodes (tests/test_sr_episodes.py)")
        self.assertEqual((REGISTRY.get("trendline_v5").version, REGISTRY.get("support_resistance").version),
                         ("trendline-first-v5.1", "sr-levels-v2"))
        self.assertEqual(REGISTRY.get("trendline_v5").lifecycle, CONFIRMED_EVENTS_LIFECYCLE, "the live trendline (v5)")
        self.assertNotIn("trendline", REGISTRY.registered(), "the retired v4 trendline is not registered")


class AnalystStopTests(unittest.TestCase):
    def test_analyst_explains_the_stop_from_stored_evidence(self):
        result = V2.evaluate(f.scenario())
        snapshot = {"setup_id": "s", "observation_id": "o", "direction": "LONG", "rule_evidence": {"strategy_valid": True},
                    "strategy_evidence": result["strategy_evidence"], "features": {}}
        analysis = analyst.analyze_snapshot(snapshot, generated_at="2026-09-25T00:00:00+00:00")
        stop_items = [item for item in analysis["evidence"] if item["category"] == "stop"]
        self.assertEqual({item["source_field"] for item in stop_items},
                         {"strategy_evidence.stop." + key for key in ("structural_invalidation", "buffer", "stop_distance", "risk_quality")})
        for item in stop_items:
            self.assertEqual(item["source_value"], result["strategy_evidence"]["stop"][item["source_field"].rsplit(".", 1)[1]])
        self.assertEqual(analysis["risk_context"]["risk_quality"], "WIDE_STRUCTURE")

    def test_trendline_analysis_has_no_stop_section(self):
        analysis = analyst.analyze_snapshot({"setup_id": "s", "observation_id": "o", "rule_evidence": {}, "features": {}},
                                            generated_at="2026-09-25T00:00:00+00:00")
        self.assertNotIn("risk_quality", analysis["risk_context"])


# ----------------------------------------------------------------------- confirmed events
def opposite(payload: dict, direction: str = "SHORT") -> dict:
    """The same strategy observing the other direction at the same price (a competing hypothesis)."""
    entry = payload["entry"]
    sign = 1 if direction == "SHORT" else -1
    return {**payload, "direction": direction, "stop_loss": entry + sign * 2, "invalidation_hint": entry + sign * 2,
            "take_profit": entry - sign * 5, "strategy_valid": False, "state": "DEVELOPING"}


class ConfirmedEventTests(IsolationTestCase):
    def confirm(self):
        developing, confirmed = V2.evaluate(f.scenario(trigger=False)), V2.evaluate(f.scenario())
        setup_id = self.store.scan(tm_market(developing))[0]["setup_id"]
        self.store.scan(tm_market(confirmed))
        self.assertEqual(self.store.events_for(setup_id)[-1]["to_state"], "CONFIRMED")
        return setup_id, confirmed

    def test_opposite_direction_becomes_a_competing_episode(self):
        setup_id, confirmed = self.confirm()
        short = self.store.scan(tm_market(opposite(confirmed)))[0]
        self.assertNotEqual(short["setup_id"], setup_id)
        self.assertEqual([e["to_state"] for e in self.store.events_for(setup_id)], ["DEVELOPING", "CONFIRMED"])
        self.store.scan(tm_market(opposite(confirmed)))
        self.assertEqual([e["to_state"] for e in self.store.events_for(setup_id)], ["DEVELOPING", "CONFIRMED"])
        current = {row["setup_id"]: row for row in self.episodes("current")}
        self.assertEqual({current[setup_id]["direction"], current[short["setup_id"]]["direction"]}, {"LONG", "SHORT"})

    def test_unconfirmed_hypothesis_is_still_invalidated_by_a_direction_change(self):
        developing = V2.evaluate(f.scenario(trigger=False))
        setup_id = self.store.scan(tm_market(developing))[0]["setup_id"]
        self.store.scan(tm_market(opposite(developing)))
        self.assertEqual(self.store.events_for(setup_id)[-1]["reason_code"], "DIRECTION_CHANGED")

    def test_confirmed_episode_resolves_at_its_confirmed_target(self):
        setup_id, confirmed = self.confirm()
        self.store.scan(tm_market(opposite(confirmed)))                    # a competing SHORT meanwhile
        self.store.scan(tm_market(opposite(confirmed), price=confirmed["take_profit"] + 0.01))
        event = self.store.events_for(setup_id)[-1]
        self.assertEqual((event["to_state"], event["reason_code"]), ("RESOLVED", "TARGET_PRICE_CROSSED"))
        self.assertEqual(event["metadata"]["levels"], "confirmation")

    def test_confirmed_stop_is_not_moved_by_later_observations(self):
        setup_id, confirmed = self.confirm()
        drifted = {**confirmed, "stop_loss": confirmed["stop_loss"] - 3, "invalidation_hint": confirmed["stop_loss"] - 3}
        self.store.scan(tm_market(drifted, price=confirmed["entry"]))       # a later observation re-plans lower
        self.assertEqual(self.store.events_for(setup_id)[-1]["to_state"], "ACTIVE")
        self.store.scan(tm_market(drifted, price=confirmed["stop_loss"] - 0.01))   # below the CONFIRMED stop only
        event = self.store.events_for(setup_id)[-1]
        self.assertEqual((event["to_state"], event["reason_code"]), ("INVALIDATED", "INVALIDATION_PRICE_CROSSED"))

    def test_confirmation_and_confirmed_plan_are_immutable(self):
        setup_id, confirmed = self.confirm()
        before = self.store.records("setup_confirmations.jsonl")
        drifted = {**confirmed, "entry": confirmed["stop_loss"] + 0.05, "rr": 79.0}
        self.store.scan(tm_market(drifted, price=confirmed["stop_loss"] + 0.05))
        self.assertEqual(self.store.records("setup_confirmations.jsonl"), before)
        row = next(r for r in self.episodes("confirmed") if r["setup_id"] == setup_id)
        plan = row["confirmed_plan"]
        self.assertEqual((plan["entry"], plan["stop_loss"], plan["take_profit"], plan["rr"]),
                         (confirmed["entry"], confirmed["stop_loss"], confirmed["take_profit"], confirmed["rr"]))
        self.assertEqual(plan["observation_id"], before[0]["observation_id"])
        self.assertEqual(row["proposed_entry"], drifted["entry"], "the row itself is the latest observation")
        self.assertEqual(plan["stop_evidence"]["risk_quality"], confirmed["strategy_evidence"]["stop"]["risk_quality"])

    def test_historical_records_are_never_rewritten(self):
        self.store.scan(tm_market(V2.evaluate(f.scenario(trigger=False))))
        path = self.store.root / "setup_observations.jsonl"
        original = path.read_bytes()
        self.store.scan(tm_market(V2.evaluate(f.scenario())), market("LONG", invalidation=2600.0))
        self.assertTrue(path.read_bytes().startswith(original))

    def test_trendline_keeps_the_original_lifecycle(self):
        first = self.store.scan(market("LONG", state="CONFIRMING", valid=True, invalidation=2600.0))[0]
        self.store.scan(market("SHORT", invalidation=2700.0))
        self.assertEqual(self.store.events_for(first["setup_id"])[-1]["reason_code"], "DIRECTION_CHANGED")

    def test_trend_momentum_never_touches_other_strategies(self):
        trend = self.store.scan(market("SHORT", invalidation=2700.0))[0]["setup_id"]
        setup_id, confirmed = self.confirm()
        self.store.scan(tm_market(opposite(confirmed), price=confirmed["take_profit"] + 0.01), market("SHORT", invalidation=2700.0))
        self.assertNotIn("RESOLVED", [e["to_state"] for e in self.store.events_for(trend)])
        self.assertEqual([e["to_state"] for e in self.store.events_for(trend)], ["DEVELOPING"])

    def episodes(self, bucket):
        with g.isolated_store(observations, self.store.root):
            return observations.setup_episodes(bucket)


# ---------------------------------------------------------------------------- A/B replay
class ReplayTests(unittest.TestCase):
    def path(self, *bars):
        return [{"time": i, "open": o, "high": h, "low": l, "close": c} for i, (o, h, l, c) in enumerate(bars)]

    def test_resolve_first_barrier(self):
        self.assertEqual(stop_ab.resolve("LONG", 100, 95, 110, self.path((100, 101, 99, 100), (100, 111, 99, 110)))["outcome"], "TARGET")
        self.assertEqual(stop_ab.resolve("LONG", 100, 95, 110, self.path((100, 101, 94, 96)))["outcome"], "STOP")
        self.assertEqual(stop_ab.resolve("SHORT", 100, 105, 90, self.path((100, 106, 99, 104)))["outcome"], "STOP")
        self.assertEqual(stop_ab.resolve("LONG", 100, 95, 110, self.path((100, 111, 94, 100)))["outcome"], "AMBIGUOUS")
        self.assertEqual(stop_ab.resolve("LONG", 100, 95, 110, self.path((100, 101, 99, 100)), horizon=1)["outcome"], "EXPIRED")
        self.assertEqual(stop_ab.resolve("LONG", 100, 95, 110, self.path((100, 101, 99, 100)), horizon=5)["outcome"], "OPEN")

    def test_summary_rates_only_where_defined(self):
        empty = stop_ab.summarize([], [])
        self.assertIsNone(empty["target_share_of_decided"])
        self.assertIsNone(empty["stop_distance_atr_h1"]["median"])

    def test_wider_stop_can_only_survive_longer(self):
        path = self.path((100, 101, 96, 97), (97, 111, 97, 110))
        a = stop_ab.resolve("LONG", 100, 96.5, 110, path)
        b = stop_ab.resolve("LONG", 100, 95.5, 110, path)
        self.assertEqual((a["outcome"], b["outcome"]), ("STOP", "TARGET"))
        compare = stop_ab.compare([{"symbol": "X", "k": 1, "direction": "LONG", "time": 0, "stop": 96.5, "rr": 2.9, "risk_atr_h1": 1, **a}],
                                  [{"symbol": "X", "k": 1, "direction": "LONG", "time": 0, "stop": 95.5, "rr": 2.2, "risk_atr_h1": 1.2, **b}])
        self.assertEqual((compare["survived_B_failed_A"], compare["survived_A_failed_B"]), (1, 0))


# ------------------------------------------------------------------------- evaluation layer
class EvaluationTests(IsolationTestCase):
    def setUp(self):
        super().setUp()
        bull, bear = V2.evaluate(f.scenario()), V2.evaluate(f.scenario(bearish=True))
        batch = self.store.scan(tm_market(bull, "XAUUSD", verified=True), tm_market(bear, "EURUSD", verified=True),
                                market("LONG", state="CONFIRMING", valid=True, invalidation=2600.0))
        self.long_id, self.short_id, self.trend_id = (m["setup_id"] for m in batch)
        self.confirmations = self.store.records("setup_confirmations.jsonl")
        self.snapshots = {s["observation_id"]: s for s in self.store.records("setup_observations.jsonl")}
        base = g.BASE_NOW.timestamp() + 60
        rising = lambda start: [{"time": base + i * 900, "open": start + 0.8 * i, "high": start + 0.8 * i + 0.3,  # noqa: E731
                                 "low": start + 0.8 * i - 0.3, "close": start + 0.8 * i} for i in range(40)]
        verified = resolve_due_market_outcomes(self.confirmations, self.snapshots, {"XAUUSD": rising(bull["entry"]),
                                               "EURUSD": rising(bear["entry"])}, [], ("1h", "4h", "24h"), now=g.BASE_NOW + timedelta(days=2))
        trend_confirmation = next(c for c in self.confirmations if c["setup_id"] == self.trend_id)
        legacy = {"record_type": "market_outcome", "setup_id": self.trend_id, "observation_id": trend_confirmation["observation_id"],
                  "horizon": "4h", "label": "WIN"}                          # no integrity proof
        self.records = evaluation.setup_records(self.confirmations, self.snapshots, [*verified, legacy])

    def test_verified_vs_unverified(self):
        by_id = {r["setup_id"]: r["outcome"] for r in self.records}
        self.assertEqual(by_id[self.long_id], "verified_target")
        self.assertEqual(by_id[self.short_id], "verified_stop")
        self.assertEqual(by_id[self.trend_id], "quarantined", "an unproven WIN is never evidence")

    def test_insufficient_sample_shows_no_rate(self):
        report = evaluation.condition_report(self.records, ["trendline", "support_resistance", "trend_momentum"])
        tm_report = next(s for s in report["strategies"] if s["strategy_id"] == "trend_momentum")
        self.assertEqual(tm_report["totals"]["status"], evaluation.INSUFFICIENT)
        self.assertIsNone(tm_report["totals"]["target_share"])
        self.assertEqual(tm_report["conditions"]["direction"]["values"]["LONG"]["verified_target"], 1)
        self.assertEqual(tm_report["conditions"]["direction"]["values"]["SHORT"]["verified_stop"], 1)
        self.assertIn("risk_quality", tm_report["conditions"])
        self.assertNotIn("risk_quality", next(s for s in report["strategies"] if s["strategy_id"] == "trendline")["conditions"])

    def test_rate_appears_only_at_the_threshold(self):
        record = lambda outcome, i: {"setup_id": str(i), "strategy_id": "trend_momentum", "confirmed_at": str(i),  # noqa: E731
                                     "outcome": outcome, "horizon": "4h", "shadow": False, "conditions": {"direction": "LONG"}}
        rows = [record("verified_target", i) for i in range(10)] + [record("verified_stop", 10 + i) for i in range(19)]
        report = evaluation.condition_report(rows, ["trend_momentum"])["strategies"][0]
        self.assertEqual(report["totals"]["status"], evaluation.INSUFFICIENT)
        rows.append(record("verified_stop", 99))
        report = evaluation.condition_report(rows, ["trend_momentum"])["strategies"][0]
        self.assertEqual((report["totals"]["status"], report["totals"]["target_share"]), ("SUFFICIENT", round(10 / 30, 3)))
        rows.extend(record(kind, 200 + i) for i, kind in enumerate(["pending", "unverified", "quarantined"] * 20))
        again = evaluation.condition_report(rows, ["trend_momentum"])["strategies"][0]["totals"]
        self.assertEqual(again["target_share"], round(10 / 30, 3), "non-verified outcomes never change the evidence")

    def test_strategies_are_never_mixed(self):
        report = {s["strategy_id"]: s for s in evaluation.condition_report(self.records, ["trendline", "trend_momentum"])["strategies"]}
        self.assertEqual(report["trendline"]["totals"]["confirmed"], 1)
        self.assertEqual(report["trend_momentum"]["totals"]["confirmed"], 2)

    def test_similar_setups_use_only_earlier_history_of_the_same_strategy(self):
        snapshot = next(s for s in self.snapshots.values() if s["setup_id"] == self.long_id and s["rule_evidence"]["strategy_valid"])
        everything = evaluation.similar_setups(snapshot, self.records)
        self.assertEqual(everything["strategy_totals"]["confirmed"], 1, "itself and other strategies excluded")
        before = evaluation.similar_setups(snapshot, self.records, before="0000")
        self.assertEqual(before["strategy_totals"]["confirmed"], 0)
        self.assertTrue(all(row["status"] == evaluation.INSUFFICIENT for row in everything["conditions"]))


# ----------------------------------------------------------------------------- API routes
class ApiTests(IsolationTestCase):
    def test_per_strategy_bound_keeps_every_strategy_in_the_feed(self):
        self.store.scan(market("LONG", symbol="EURUSD", invalidation=1.0), market("LONG", symbol="GBPUSD", invalidation=1.0),
                        tm_market(V2.evaluate(f.scenario(trigger=False))))
        with g.isolated_store(observations, self.store.root):
            plain = observations.setup_episodes("current", limit=1)
            bounded = observations.setup_episodes("current", limit=1, per_strategy=True)
        self.assertEqual(len(plain), 1)
        self.assertEqual(sorted(row["strategy_id"] for row in bounded), ["trend_momentum", "trendline"])

    def test_evaluation_and_similar_routes(self):
        import main
        setup_id = self.store.scan(tm_market(V2.evaluate(f.scenario()), verified=True))[0]["setup_id"]
        with g.isolated_store(observations, self.store.root),                 unittest.mock.patch.object(main, "MARKET_OUTCOMES_FILE", self.store.root / "market_outcomes.jsonl"):
            main._EVALUATION_CACHE.update(key=None, records=None)
            report = main.historical_evaluation()
            similar = main.similar_setups(setup_id)
        tm_report = next(s for s in report["strategies"] if s["strategy_id"] == "trend_momentum")
        self.assertEqual(tm_report["totals"]["confirmed"], 1)
        self.assertEqual(tm_report["totals"]["status"], evaluation.INSUFFICIENT)
        self.assertEqual((similar["setup_id"], similar["basis"]), (setup_id, "confirmation snapshot"))
        self.assertEqual(similar["strategy_totals"]["confirmed"], 0, "no earlier history; never itself")


# ------------------------------------------------------------------------------- mutations
MUTATIONS = {
    "stop placed on the structure": ([unittest.mock.patch.object(tm, "stop_buffer", lambda *args: 0.0)],
                                     ["StopModelTests.test_structural_stop_beyond_the_pullback_extreme_with_the_atr_buffer"]),
    "buffer ignores M15 volatility": ([unittest.mock.patch.object(tm, "M15_BUFFER_ATR", 0.0)],
                                      ["StopModelTests.test_buffer_is_clamped_between_quarter_and_half_an_h1_atr"]),
    "buffer cap removed": ([unittest.mock.patch.object(tm, "MAX_BUFFER_ATR", 100.0)],
                           ["StopModelTests.test_buffer_is_clamped_between_quarter_and_half_an_h1_atr"]),
    "risk envelope removed": ([unittest.mock.patch.object(tm, "MAX_RISK_ATR", 1e9)],
                              ["StopModelTests.test_genuinely_wide_structure_fixture_is_rejected"]),
    "noise floor removed": ([unittest.mock.patch.object(tm, "MIN_RISK_ATR", 0.0)],
                            ["StopModelTests.test_a_1_to_79_style_plan_is_never_confirmed"]),
    "confirmed-event lifecycle off": ([unittest.mock.patch.object(observations, "_confirmed_events_policy", lambda *args: False)],
                                      ["ConfirmedEventTests.test_opposite_direction_becomes_a_competing_episode",
                                       "ConfirmedEventTests.test_confirmed_episode_resolves_at_its_confirmed_target",
                                       "ConfirmedEventTests.test_confirmed_stop_is_not_moved_by_later_observations"]),
    "confirmed plan read from the latest observation": (
        [unittest.mock.patch.object(observations, "confirmed_plans",
                                    lambda ids: {})],
        ["ConfirmedEventTests.test_confirmation_and_confirmed_plan_are_immutable",
         "ConfirmedEventTests.test_confirmed_stop_is_not_moved_by_later_observations"]),
    "confirmed-event lifecycle applied to trendline": ([unittest.mock.patch.object(observations, "_confirmed_events_policy", lambda *args: True)],
                                                        ["ConfirmedEventTests.test_trendline_keeps_the_original_lifecycle"]),
    "unverified outcomes counted as evidence": ([unittest.mock.patch.object(evaluation, "classify_outcome",
                                                 lambda c, own, snap: ("verified_target", "4h") if own else ("pending", None))],
                                                ["EvaluationTests.test_verified_vs_unverified"]),
    "sample threshold removed": ([unittest.mock.patch.object(evaluation, "MIN_VERIFIED", 0)],
                                 ["EvaluationTests.test_insufficient_sample_shows_no_rate", "EvaluationTests.test_rate_appears_only_at_the_threshold"]),
    "similar setups include later history": ([unittest.mock.patch.object(evaluation, "similar_setups",
                                              lambda snapshot, records, before=None: _similar(snapshot, records, None))],
                                             ["EvaluationTests.test_similar_setups_use_only_earlier_history_of_the_same_strategy"]),
}
_similar = evaluation.similar_setups


class MutationTests(unittest.TestCase):
    def run_named(self, names, patches=()):
        suite = unittest.defaultTestLoader.loadTestsFromNames([__name__ + "." + name for name in names])
        result = unittest.TestResult()
        from contextlib import ExitStack
        with ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            suite.run(result)
        return result

    def test_every_mutation_is_caught(self):
        for name, (patches, targets) in MUTATIONS.items():
            with self.subTest(mutation=name):
                self.assertTrue(self.run_named(targets).wasSuccessful(), "the targeted tests pass unmutated")
                mutated = self.run_named(targets, patches)
                self.assertFalse(mutated.wasSuccessful(), "mutation not caught")


if __name__ == "__main__":
    unittest.main()
