"""Phase 10: Trend / Momentum strategy (tm-pullback-v1; SHADOW in Phase 10, LIVE since Phase 10b).

Rules are tested on explicit synthetic multi-timeframe paths (tests/tm_fixtures.py);
the bearish cases are exact price mirrors of the bullish ones. Persistence,
lifecycle, research mode and isolation go through the real record_markets and
main.market_snapshot. Every expected level below is recomputed in the test from
the bars themselves, not copied from the strategy's output.
"""
from __future__ import annotations

import ast
import copy
import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g  # noqa: E402
import tm_fixtures as f  # noqa: E402

import observations  # noqa: E402
import strategy_lab  # noqa: E402
from outcomes import resolve_due_market_outcomes  # noqa: E402
from performance import performance_report  # noqa: E402
from strategies import (LIVE, SHADOW, REGISTRY, StrategyRegistry, SupportResistanceStrategy,  # noqa: E402
                        TrendMomentumStrategy, build_default_registry)
from strategies import trend_momentum as tm  # noqa: E402
from test_market_data import IC_MARKETS, FakeBroker, run_scan  # noqa: E402
from test_strategy_isolation import IsolationTestCase, market  # noqa: E402

STRATEGY = TrendMomentumStrategy()


def evaluate(**kwargs) -> dict:
    return STRATEGY.evaluate(f.scenario(**kwargs))


def tm_market(payload: dict, symbol: str = "XAUUSD", price: float | None = None, verified: bool = False) -> dict:
    """The market dict main builds for a non-trendline strategy result."""
    last = payload.get("entry") or 110.0
    row = {"symbol": symbol, "broker_symbol": symbol, "price": price if price is not None else last, "bid": last, "ask": last,
           "spread": 0.0, "change_pct": 0.0, **payload, "timeframe": "M15", "higher_timeframes": ["H1", "H4", "D1"],
           "strategy_id": "trend_momentum", "strategy_version": payload["strategy_version"], "strategy_mode": "LIVE"}
    if verified:
        row.update(time_provenance={"source_time_basis": "UTC", "timezone_normalization_status": "VERIFIED"},
                   source_timestamp=g.BASE_NOW.isoformat())
    return row


def closed(frames, timeframe):
    return frames[timeframe][:-1]


def h1_structure(frames, long=True):
    """Impulse extreme, origin and pullback extreme recomputed from the closed H1 bars."""
    bars = closed(frames, "H1")
    n = len(bars)
    key, other = ("high", "low") if long else ("low", "high")
    pick = max if long else min
    extreme = pick(b[key] for b in bars[n - 30:])
    ih = max(i for i in range(n - 30, n) if bars[i][key] == extreme)
    origin = (min if long else max)(b[other] for b in bars[max(0, ih - 30):ih])
    pullback = (min if long else max)(b[other] for b in bars[ih + 1:])
    return extreme, origin, pullback


# ------------------------------------------------------------------------------------ rules
class ContinuationTests(unittest.TestCase):
    def test_bullish_continuation_after_controlled_pullback_confirms(self):
        result = evaluate()
        self.assertEqual((result["state"], result["direction"], result["strategy_valid"]), ("CONFIRMING", "LONG", True))
        self.assertEqual(result["setup_family"], "TM_PULLBACK_CONTINUATION")
        self.assertEqual(result["strategy_version"], "tm-pullback-v1")
        rules = result["strategy_evidence"]["confirmation"]["rules"]
        self.assertEqual(tuple(rules), tm.CONFIRMATION_RULES)
        self.assertTrue(all(rules.values()))
        self.assertEqual(result["strategy_evidence"]["trend"]["h4"]["structure"], "HIGHER_HIGHS_HIGHER_LOWS")
        self.assertEqual(result["strategy_evidence"]["trend"]["d1"]["status"], "AGREES")
        self.assertTrue(result["strategy_evidence"]["trigger"]["resumption"])

    def test_bearish_continuation_is_the_exact_mirror(self):
        bull, bear = evaluate(), evaluate(bearish=True)
        self.assertEqual((bear["state"], bear["direction"], bear["strategy_valid"]), ("CONFIRMING", "SHORT", True))
        self.assertEqual(bear["strategy_evidence"]["trend"]["h4"]["structure"], "LOWER_HIGHS_LOWER_LOWS")
        for key in ("entry", "stop_loss", "take_profit"):
            self.assertAlmostEqual(bear[key], f.MIRROR_AXIS - bull[key], places=9)
        self.assertEqual((bear["rr"], bear["score"], bear["score_breakdown"]), (bull["rr"], bull["score"], bull["score_breakdown"]))

    def test_controlled_pullback_without_a_trigger_is_developing(self):
        for kwargs in ({"trigger": False}, {"lift": 0.02}):
            result = evaluate(**kwargs)
            with self.subTest(**kwargs):
                self.assertEqual((result["state"], result["strategy_valid"]), ("DEVELOPING", False))
                self.assertEqual(result["strategy_evidence"]["confirmation"]["failed"], ["resumption"])
                self.assertIsNotNone(result["stop_loss"])      # the plan is known; the setup is not confirmed
        self.assertEqual(evaluate(trigger=False, bearish=True)["state"], "DEVELOPING")


class RejectionTests(unittest.TestCase):
    def test_insufficient_impulse_is_not_a_setup_candidate(self):
        result = evaluate(impulse_step=0.02, base_trend=0.01, wiggle=0.02, alternation=0.0)
        momentum = result["strategy_evidence"]["momentum"]
        self.assertLess(momentum["impulse_atr"], tm.MIN_IMPULSE_ATR)
        self.assertEqual((result["state"], result["strategy_valid"]), ("WATCHING", False))
        self.assertFalse(result["strategy_evidence"]["confirmation"]["rules"]["impulse"])
        self.assertIsNone(result["entry"])

    def test_choppy_impulse_lacks_persistence(self):
        result = evaluate(choppy=True)
        self.assertLess(result["strategy_evidence"]["momentum"]["efficiency"], tm.MIN_EFFICIENCY)
        self.assertGreaterEqual(result["strategy_evidence"]["momentum"]["impulse_atr"], tm.MIN_IMPULSE_ATR)
        self.assertEqual((result["state"], result["strategy_valid"]), ("WATCHING", False))
        self.assertFalse(result["strategy_evidence"]["confirmation"]["rules"]["persistence"])

    def test_failed_pullback_is_no_setup(self):
        for kwargs in ({"retracement": 0.8}, {"retracement": 0.8, "bearish": True}):
            result = evaluate(**kwargs)
            with self.subTest(**kwargs):
                self.assertEqual((result["state"], result["direction"], result["strategy_valid"]), ("NO SETUP", None, False))
                self.assertIn("Pullback failed", result["reason"])
                self.assertGreater(result["strategy_evidence"]["pullback"]["retracement"], tm.MAX_RETRACEMENT)

    def test_no_pullback_yet_and_stale_impulse_only_watch(self):
        early = evaluate(pullback_bars=1, retracement=0.1)
        self.assertEqual((early["state"], early["strategy_valid"]), ("WATCHING", False))
        self.assertFalse(early["strategy_evidence"]["pullback"]["started"])
        stale = evaluate(pullback_bars=18, retracement=0.4)
        self.assertEqual((stale["state"], stale["strategy_valid"]), ("WATCHING", False))
        self.assertTrue(stale["strategy_evidence"]["pullback"]["stale"])

    def test_retracement_band_edges(self):
        for retracement in (0.3, 0.6):
            self.assertTrue(evaluate(retracement=retracement)["strategy_valid"], retracement)
        self.assertEqual(evaluate(retracement=0.7)["state"], "NO SETUP")

    def test_higher_timeframe_disagreement(self):
        d1 = evaluate(d1_trend=-0.3)
        self.assertEqual((d1["state"], d1["strategy_valid"]), ("NO SETUP", False))
        self.assertEqual(d1["strategy_evidence"]["trend"]["d1"]["status"], "OPPOSES")
        flat = evaluate(h4_trend=0.0)
        self.assertEqual(flat["state"], "NO SETUP")
        self.assertIsNone(flat["strategy_evidence"]["trend"]["h4"]["direction"])
        h1 = evaluate(base_trend=-0.1, impulse_step=-0.4)
        self.assertEqual(h1["state"], "NO SETUP")
        self.assertFalse(h1["strategy_evidence"]["trend"]["h1"]["aligned"])
        mirrored = evaluate(d1_trend=-0.3, bearish=True)              # the mirror of a falling D1 is a rising D1
        self.assertEqual((mirrored["state"], mirrored["strategy_evidence"]["trend"]["d1"]["status"]), ("NO SETUP", "OPPOSES"))

    def test_missing_d1_history_is_recorded_and_never_vetoes(self):
        scenario = f.scenario()
        bars = {**scenario.bars, "D1": scenario.bars["D1"][-20:]}
        result = STRATEGY.evaluate(f.MarketInput("TEST", scenario.rows, higher_rows=scenario.higher_rows, bars=bars))
        self.assertEqual(result["strategy_evidence"]["trend"]["d1"]["status"], "UNAVAILABLE")
        self.assertTrue(result["strategy_valid"])
        self.assertEqual(result["score_breakdown"]["d1_context"], 5)

    def test_insufficient_history_is_no_setup(self):
        scenario = f.scenario()
        for timeframe in ("M15", "H1", "H4"):
            bars = {**scenario.bars, timeframe: scenario.bars[timeframe][-20:]}
            result = STRATEGY.evaluate(f.MarketInput("TEST", bars["M15"], higher_rows=bars["H1"], bars=bars))
            self.assertEqual(result["state"], "NO SETUP", timeframe)
            self.assertIn("Insufficient " + timeframe, result["reason"])


# ------------------------------------------------------------------------------------- plan
class PlanTests(unittest.TestCase):
    def check_plan(self, bearish: bool):
        scenario = f.scenario(bearish=bearish)
        result = STRATEGY.evaluate(scenario)
        frames = scenario.bars
        long = not bearish
        extreme, origin, pullback = h1_structure(frames, long)
        unit = tm.atr(closed(frames, "H1"))
        impulse = abs(extreme - origin)
        entry = frames["M15"][-1]["close"]
        stop = pullback - 0.25 * unit if long else pullback + 0.25 * unit
        target = pullback + impulse if long else pullback - impulse
        self.assertEqual(result["entry"], entry)                                   # entry: the current (forming M15) price
        self.assertAlmostEqual(result["stop_loss"], stop, places=9)                # stop: beyond the pullback extreme
        self.assertAlmostEqual(result["take_profit"], target, places=9)            # target: measured move from the pullback
        self.assertEqual(result["invalidation_hint"], result["stop_loss"])
        risk, reward = abs(entry - stop), abs(target - entry)
        self.assertEqual(result["rr"], round(reward / risk, 2))
        self.assertAlmostEqual(result["risk_distance"], risk, places=9)
        self.assertAlmostEqual(result["reward_distance"], reward, places=9)
        self.assertEqual(result["strategy_evidence"]["plan"]["structure_invalidation"], pullback)
        self.assertTrue(tm.MIN_RISK_ATR * unit <= risk <= tm.MAX_RISK_ATR * unit)
        self.assertLess(entry, extreme) if long else self.assertGreater(entry, extreme)

    def test_entry_stop_target_and_rr_long(self):
        self.check_plan(bearish=False)

    def test_entry_stop_target_and_rr_short(self):
        self.check_plan(bearish=True)

    def test_insufficient_reward_blocks_confirmation(self):
        result = evaluate(impulse_step=0.1)            # triggered, but the entry is past the impulse high and R < 1.5
        self.assertEqual(result["state"], "CONFIRMING")
        self.assertFalse(result["strategy_valid"])
        self.assertIn("min_rr", result["strategy_evidence"]["confirmation"]["failed"])
        self.assertLess(result["rr"], tm.MIN_RR)

    def test_levels_are_absent_before_a_pullback_candidate(self):
        for kwargs in ({"pullback_bars": 1, "retracement": 0.1}, {"choppy": True}, {"d1_trend": -0.3}):
            result = evaluate(**kwargs)
            self.assertEqual((result["entry"], result["stop_loss"], result["take_profit"], result["rr"]), (None, None, None, None), kwargs)


# ------------------------------------------------------------------------------ score/evidence
class ScoreEvidenceTests(unittest.TestCase):
    def test_score_is_the_sum_of_bounded_stored_components(self):
        for kwargs in ({}, {"bearish": True}, {"trigger": False}, {"choppy": True}, {"retracement": 0.3}, {"pullback_bars": 1, "retracement": 0.1}):
            result = evaluate(**kwargs)
            components = result["strategy_evidence"]["score_components"]
            with self.subTest(**kwargs):
                self.assertEqual(set(components), set(result["score_breakdown"]))
                self.assertEqual(result["score"], sum(result["score_breakdown"].values()))
                self.assertLessEqual(result["score"], 100)
                for name, part in components.items():
                    self.assertEqual(part["points"], result["score_breakdown"][name])
                    self.assertTrue(0 <= part["points"] <= part["max"], name)
                    self.assertIn("measure", part)

    def test_score_components_follow_their_documented_formulas(self):
        result = evaluate(retracement=0.3)
        evidence = result["strategy_evidence"]
        slope, efficiency = evidence["trend"]["h4"]["ema50_slope_atr"], evidence["momentum"]["efficiency"]
        expected = {"h4_trend": round(20 * min(1, abs(slope))), "persistence": round(25 * min(1, efficiency / 0.7)),
                    "impulse": round(15 * min(1, evidence["momentum"]["impulse_atr"] / 4)),
                    "pullback": 12,                                   # 0.3 is controlled but outside the 0.382-0.5 band
                    "d1_context": 10, "risk_reward": 10 if result["rr"] >= 2 else 5}
        self.assertEqual(result["score_breakdown"], expected)
        self.assertEqual(evaluate()["score_breakdown"]["pullback"], 20)        # 0.45: inside the band

    def test_score_never_decides_state_or_confirmation(self):
        choppy = evaluate(choppy=True)
        self.assertGreater(choppy["score"], 50)
        self.assertFalse(choppy["strategy_valid"])                  # a decent score does not confirm anything
        weak = evaluate(impulse_step=0.1)
        self.assertGreater(weak["score"], 70)
        self.assertFalse(weak["strategy_valid"])

    def test_evidence_records_every_rule_and_parameter(self):
        evidence = evaluate()["strategy_evidence"]
        for key in ("method", "setup_timeframe", "trigger_timeframe", "parameters", "trend", "momentum", "pullback", "trigger",
                    "confirmation", "plan", "score_components", "atr"):
            self.assertIn(key, evidence)
        self.assertEqual((evidence["setup_timeframe"], evidence["trigger_timeframe"]), ("H1", "M15"))
        self.assertEqual(evidence["parameters"]["min_rr"], tm.MIN_RR)
        json.dumps(evidence)                                          # persisted as is: must be JSON-serialisable


class DeterminismTests(unittest.TestCase):
    def test_same_input_same_output_and_no_input_mutation(self):
        scenario = f.scenario()
        before = copy.deepcopy(scenario)
        self.assertEqual(STRATEGY.evaluate(scenario), STRATEGY.evaluate(scenario))
        self.assertEqual(scenario, before)

    def test_only_closed_bars_decide_structure(self):
        scenario = f.scenario()
        bars = {tf: [dict(row) for row in rows] for tf, rows in scenario.bars.items()}
        for timeframe in ("H1", "H4", "D1"):
            bars[timeframe][-1].update(high=bars[timeframe][-1]["high"] + 50, low=bars[timeframe][-1]["low"] - 50)
        result = STRATEGY.evaluate(f.MarketInput("TEST", bars["M15"], higher_rows=bars["H1"], bars=bars))
        self.assertEqual(result, STRATEGY.evaluate(scenario))

    def test_the_module_is_independent_of_the_other_strategies(self):
        tree = ast.parse(Path(tm.__file__).read_text(encoding="utf-8"))
        imported = {"." * node.level + (node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | \
                   {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertFalse(imported & {"scanner", "support_resistance", ".support_resistance", "trendline", ".trendline"}, imported)
        self.assertLessEqual(imported, {"__future__", "typing", "episode_identity", ".base"})


# --------------------------------------------------------------------------- lifecycle/persistence
class PersistenceLifecycleTests(IsolationTestCase):
    def test_snapshots_carry_their_own_identity(self):
        batch = self.store.scan(tm_market(evaluate(trigger=False)))
        snapshot = self.store.records("setup_observations.jsonl")[0]
        self.assertEqual((snapshot["strategy_id"], snapshot["strategy_version"], snapshot.get("shadow")),
                         ("trend_momentum", "tm-pullback-v1", None))                      # LIVE: no research flag
        self.assertEqual(snapshot["episode_identity"]["strategy_id"], "trend_momentum")
        self.assertEqual(snapshot["setup_type"], "TM_PULLBACK_CONTINUATION")
        self.assertEqual(snapshot["timeframe"], "M15")
        self.assertEqual(snapshot["strategy_evidence"]["setup_timeframe"], "H1")
        self.assertEqual(snapshot["score_breakdown"], evaluate(trigger=False)["score_breakdown"])
        self.assertEqual(snapshot["lifecycle_state"], "DEVELOPING")
        self.assertEqual(batch[0]["setup_id"], snapshot["setup_id"])

    def test_lifecycle_developing_confirmed_then_invalidated(self):
        developing, confirmed = evaluate(trigger=False), evaluate()
        first = self.store.scan(tm_market(developing))[0]["setup_id"]
        second = self.store.scan(tm_market(confirmed))[0]["setup_id"]
        self.assertEqual(first, second, "the continuation of one pullback is one episode")
        broken = self.store.scan(tm_market(developing, price=confirmed["stop_loss"] - 0.01))
        events = self.store.events_for(first)
        self.assertEqual([e["to_state"] for e in events], ["DEVELOPING", "CONFIRMED", "INVALIDATED"])
        self.assertEqual(events[-1]["reason_code"], "INVALIDATION_PRICE_CROSSED")
        # Existing lifecycle rule: unchanged evidence does not immediately reopen a just-closed episode.
        self.assertEqual((broken[0]["setup_id"], broken[0]["episode_suppressed"]), (first, True))
        confirmations = self.store.records("setup_confirmations.jsonl")
        self.assertEqual([(c["setup_id"], c["strategy_id"], c["strategy_version"], c.get("shadow")) for c in confirmations],
                         [(first, "trend_momentum", "tm-pullback-v1", None)])

    def test_watching_is_a_candidate_never_a_confirmation(self):
        self.store.scan(tm_market(evaluate(pullback_bars=1, retracement=0.1), price=115.0))
        self.assertEqual(self.store.records("setup_observations.jsonl")[0]["lifecycle_state"], "DETECTED")
        self.assertEqual(self.store.records("setup_confirmations.jsonl"), [])

    def test_no_setup_closes_only_its_own_episode(self):
        setup_id = self.store.scan(tm_market(evaluate(trigger=False)), market("LONG", invalidation=2600.0))[0]["setup_id"]
        trend_id = self.store.records("setup_observations.jsonl")[1]["setup_id"]
        self.store.scan(tm_market(evaluate(d1_trend=-0.3), price=109.9), market("LONG", invalidation=2600.0))
        self.assertEqual(self.store.events_for(setup_id)[-1]["to_state"], "INVALIDATED")
        self.assertEqual([e["to_state"] for e in self.store.events_for(trend_id)], ["DEVELOPING"])


class ResearchModeTests(IsolationTestCase):
    """Trend / Momentum is LIVE; SHADOW (research) mode stays available for future experimental
    strategies. Its guarantees are exercised here with trend_momentum registered in research
    mode, as it was in Phase 10."""

    def setUp(self):
        super().setUp()
        self.research = g.research_mode(observations)
        self.registry = self.research.__enter__()

    def tearDown(self):
        self.research.__exit__(None, None, None)
        super().tearDown()

    def test_registered_live_and_research_mode_still_available(self):
        self.assertEqual(REGISTRY.mode("trend_momentum"), LIVE)
        self.assertIn("trend_momentum", REGISTRY.live())
        self.assertEqual(REGISTRY.get("trend_momentum").version, "tm-pullback-v1")
        self.assertEqual(self.registry.mode("trend_momentum"), SHADOW)

    def test_research_confirmations_are_never_live(self):
        self.store.scan(tm_market(evaluate()), market("LONG", state="CONFIRMING", valid=True, invalidation=2600.0))
        confirmations = self.store.records("setup_confirmations.jsonl")
        by_strategy = {c["strategy_id"]: c for c in confirmations}
        self.assertTrue(by_strategy["trend_momentum"]["shadow"])
        self.assertNotIn("shadow", by_strategy["trendline"])
        report = performance_report(confirmations, [], self.store.records("setup_observations.jsonl"),
                                    report_date=g.BASE_NOW.date().isoformat(), days=1)
        day = report["daily"][0]
        self.assertEqual({s.get("strategy_id") or "trendline" for s in day["setups"]}, {"trendline"}, "live list: trendline only")
        self.assertIn("trend_momentum", day["by_strategy"])
        self.assertIn("trend_momentum", day["shadow_strategies"])
        with g.isolated_store(observations, self.store.root):
            self.assertEqual({e["strategy_id"] for e in observations.setup_episodes("all", 100)}, {"trendline"})
            self.assertIn("trend_momentum", {e["strategy_id"] for e in observations.setup_episodes("all", 100, include_shadow=True)})


class IsolationTests(IsolationTestCase):
    def rounds(self, *batches):
        ids = []
        for batch in batches:
            ids.append([m.get("setup_id") for m in self.store.scan(*batch)])
        return ids

    def assertNoTerminalEvents(self, setup_id):
        self.assertFalse([e for e in self.store.events_for(setup_id) if e["to_state"] in ("INVALIDATED", "EXPIRED")])

    def test_simultaneous_trendline_and_trend_momentum_same_symbol(self):
        for tl_direction, bearish in (("LONG", False), ("SHORT", False), ("LONG", True)):
            with self.subTest(trendline=tl_direction, tm_short=bearish):
                self.store.close()
                self.store = type(self.store)()
                payload = evaluate(trigger=False, bearish=bearish)
                price = payload["entry"]
                trendline = market(tl_direction, price=price, invalidation=price - 50 if tl_direction == "LONG" else price + 50)
                ids = self.rounds([trendline, tm_market(payload)], [trendline, tm_market(payload)])
                self.assertEqual(ids[0], ids[1], "both episodes continue")
                self.assertNotEqual(ids[0][0], ids[0][1])
                for setup_id in ids[0]:
                    self.assertNoTerminalEvents(setup_id)

    def test_simultaneous_support_resistance_and_trend_momentum(self):
        payload = evaluate(trigger=False)
        sr = {**tm_market(payload), "strategy_id": "support_resistance", "strategy_version": "sr-levels-v1",
              "direction": "SHORT", "setup_family": "SR_BOUNCE", "invalidation_hint": payload["entry"] + 50, "stop_loss": payload["entry"] + 50}
        ids = self.rounds([sr, tm_market(payload)], [sr, tm_market(payload)])
        self.assertEqual(ids[0], ids[1])
        for setup_id in ids[0]:
            self.assertNoTerminalEvents(setup_id)

    def test_a_trendline_direction_change_never_touches_trend_momentum(self):
        payload = evaluate(trigger=False)
        tm_id = self.store.scan(tm_market(payload), market("LONG", price=payload["entry"], invalidation=payload["entry"] - 50))[0]["setup_id"]
        self.store.scan(tm_market(payload), market("SHORT", price=payload["entry"], invalidation=payload["entry"] + 50))
        self.assertNoTerminalEvents(tm_id)
        trend_events = [e for e in self.store.records("setup_lifecycle.jsonl") if e["reason_code"] == "DIRECTION_CHANGED"]
        self.assertEqual(len(trend_events), 1)
        self.assertNotEqual(trend_events[0]["setup_id"], tm_id)

    def test_a_closed_trend_momentum_episode_never_suppresses_trendline(self):
        payload = evaluate(trigger=False)
        tm_id = self.store.scan(tm_market(payload))[0]["setup_id"]
        self.store.scan(tm_market(payload, price=payload["stop_loss"] - 0.01))          # TM invalidated
        self.assertEqual(self.store.events_for(tm_id)[-1]["to_state"], "INVALIDATED")
        row = self.store.scan(market("LONG", price=payload["entry"], anchors=None, family="REVERSAL", invalidation=payload["entry"] - 50))[0]
        self.assertFalse(row.get("episode_suppressed"))
        self.assertNotEqual(row["setup_id"], tm_id)


# ------------------------------------------------------------------------------- outcomes / lab
class OutcomeTests(IsolationTestCase):
    def test_strategy_lab_reports_trend_momentum_separately(self):
        bull, bear = evaluate(), evaluate(bearish=True)
        batch = self.store.scan(tm_market(bull, "XAUUSD", verified=True), tm_market(bear, "EURUSD", verified=True),
                                tm_market(evaluate(trigger=False), "GBPUSD", verified=True),
                                market("LONG", state="CONFIRMING", valid=True, invalidation=2600.0))
        confirmations = self.store.records("setup_confirmations.jsonl")
        snapshots = {s["observation_id"]: s for s in self.store.records("setup_observations.jsonl")}
        base = g.BASE_NOW.timestamp() + 60
        rising = lambda start: [{"time": base + i * 900, "open": start + 0.8 * i, "high": start + 0.8 * i + 0.3,  # noqa: E731
                                 "low": start + 0.8 * i - 0.3, "close": start + 0.8 * i} for i in range(40)]
        outcomes = resolve_due_market_outcomes(confirmations, snapshots, {"XAUUSD": rising(bull["entry"]), "EURUSD": rising(bear["entry"])},
                                               [], ("1h", "4h", "24h"), now=g.BASE_NOW + timedelta(days=2))
        with g.isolated_store(observations, self.store.root):
            report = {item["strategy_id"]: item for item in strategy_lab.strategy_lab_report(outcomes)["strategies"]}
        research = report["trend_momentum"]
        self.assertEqual((research["mode"], research["version"]), ("LIVE", "tm-pullback-v1"))
        self.assertEqual(research["setups"]["total"], 3)
        self.assertEqual(research["confirmations"], 2)
        self.assertEqual((research["outcomes"]["verified_target"], research["outcomes"]["verified_stop"]), (1, 1))
        self.assertIsNone(research["win_rate"], "below the minimum verified sample")
        self.assertEqual(set(research["by_instrument"]), {"XAUUSD", "EURUSD", "GBPUSD"})
        self.assertEqual(set(research["by_direction"]), {"LONG", "SHORT"})
        self.assertEqual(set(research["by_setup_type"]), {"TM_PULLBACK_CONTINUATION"})
        self.assertEqual(set(research["by_timeframe"]), {"M15"})
        self.assertEqual(report["trendline"]["setups"]["total"], 1)                       # never combined
        self.assertEqual(report["trendline"]["outcomes"]["verified_target"] + report["trendline"]["outcomes"]["verified_stop"], 0)
        self.assertEqual(report["support_resistance"]["setups"]["total"], 0)
        self.assertEqual(batch[2]["lifecycle_state"], "DEVELOPING")


# ------------------------------------------------------------------------------- end to end
class ScenarioBroker(FakeBroker):
    """FakeBroker whose chosen symbols serve synthetic trend/momentum frames."""

    def __init__(self, scenarios: dict):
        super().__init__(IC_MARKETS)
        self.frames = {name: dict(scenario.bars) for name, scenario in scenarios.items()}

    def symbol_info_tick(self, name):
        if name in self.frames:
            close = self.frames[name]["M15"][-1]["close"]
            return SimpleNamespace(bid=close, ask=close, time_msc=0, time=0)
        return super().symbol_info_tick(name)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        if symbol in self.frames:
            name = {15: "M15", 60: "H1", 240: "H4", 1440: "D1"}[timeframe]
            return [dict(row) for row in self.frames[symbol][name]][-count:]
        return super().copy_rates_from_pos(symbol, timeframe, start, count)


def trendline_and_sr():
    registry = g.trendline_only_registry()
    registry.register(SupportResistanceStrategy(), enabled=True, mode=LIVE)
    return registry


class EndToEndTests(unittest.TestCase):
    SCENARIOS = {"XAUUSD": {}, "EURUSD": {"bearish": True}, "GBPUSD": {"trigger": False}}

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        broker = lambda: ScenarioBroker({s: f.scenario(symbol=s, **kw) for s, kw in cls.SCENARIOS.items()})  # noqa: E731
        watch = list(cls.SCENARIOS) + ["NAS100"]
        cls.trendline_only = run_scan(broker(), g.trendline_only_registry(), watchlist=watch, root=root / "a")
        cls.with_sr = run_scan(broker(), trendline_and_sr(), watchlist=watch, root=root / "b")
        cls.full = run_scan(broker(), build_default_registry(), watchlist=watch, root=root / "c")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def records(self, files, name="setup_observations.jsonl"):
        return [json.loads(line) for line in files.get(name, b"").splitlines()]

    def test_trend_momentum_produces_live_results_in_the_scan(self):
        markets, files = self.full
        entries = {m["symbol"]: {e["strategy_id"]: e for e in m["strategies"]} for m in markets}
        self.assertEqual({s: e["trend_momentum"]["state"] for s, e in entries.items()},
                         {"XAUUSD": "CONFIRMING", "EURUSD": "CONFIRMING", "GBPUSD": "DEVELOPING", "NAS100": "NO SETUP"})
        self.assertEqual({e["trend_momentum"]["mode"] for e in entries.values()}, {"LIVE"})
        self.assertTrue(entries["XAUUSD"]["trend_momentum"]["confirmed"])
        snapshots = [r for r in self.records(files) if r["strategy_id"] == "trend_momentum"]
        self.assertEqual(sorted(r["symbol"] for r in snapshots), ["EURUSD", "GBPUSD", "XAUUSD"])
        self.assertFalse(any(r.get("shadow") for r in snapshots))
        confirmations = [c for c in self.records(files, "setup_confirmations.jsonl") if c["strategy_id"] == "trend_momentum"]
        self.assertEqual(len(confirmations), 2)
        self.assertFalse(any(c.get("shadow") for c in confirmations))

    def test_trendline_markets_and_records_are_unchanged(self):
        strip = lambda rows: [{k: v for k, v in m.items() if k != "strategies"} for m in rows]  # noqa: E731
        (base, base_files), (markets, files) = self.trendline_only, self.full
        self.assertEqual(g.canonical(strip(markets)), g.canonical(strip(base)), "top-level markets are the trendline result")
        for name in g.PERSISTED_FILES:
            lines = files.get(name, b"").splitlines(keepends=True)
            ids = {r["setup_id"] for r in self.records(files) if r["strategy_id"] == "trendline"}
            own = [line for line in lines if json.loads(line).get("setup_id") in ids]
            self.assertEqual(b"".join(own), base_files.get(name, b""), name)
        for market_row, base_row in zip(markets, base):
            trend = next(e for e in market_row["strategies"] if e["strategy_id"] == "trendline")
            self.assertEqual(trend, base_row["strategies"][0])

    def test_support_resistance_results_are_unchanged(self):
        (sr_markets, sr_files), (markets, files) = self.with_sr, self.full
        for a, b in zip(sr_markets, markets):
            pick = lambda row: next(e for e in row["strategies"] if e["strategy_id"] == "support_resistance")  # noqa: E731
            ids = ("setup_id", "observation_id")
            self.assertEqual({k: v for k, v in pick(a).items() if k not in ids}, {k: v for k, v in pick(b).items() if k not in ids})
        ids = ("setup_id", "observation_id", "triggering_observation_id", "event_id", "confirmation_event_id")
        strip = lambda rows: [{k: v for k, v in r.items() if k not in ids} for r in rows if r.get("strategy_id") == "support_resistance"]  # noqa: E731
        self.assertEqual(strip(self.records(sr_files)), strip(self.records(files)))

    def test_live_confirmations_are_strategy_specific(self):
        _, files = self.full
        confirmations = self.records(files, "setup_confirmations.jsonl")
        report = performance_report(confirmations, [], self.records(files), report_date=g.BASE_NOW.date().isoformat(), days=1)
        day = report["daily"][0]
        live = [(s["strategy_id"], s["symbol"], s["direction"]) for s in day["setups"] if s.get("strategy_id") == "trend_momentum"]
        self.assertEqual(sorted(live), [("trend_momentum", "EURUSD", "SHORT"), ("trend_momentum", "XAUUSD", "LONG")])
        self.assertEqual(day["shadow_strategies"], [])
        self.assertIn("trend_momentum", day["by_strategy"])


if __name__ == "__main__":
    unittest.main()
