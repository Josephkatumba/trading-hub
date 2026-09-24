"""Phase 6: Support & Resistance strategy, shadow mode.

Deterministic synthetic markets (tests/sr_fixtures.py) exercise every rule of
strategies/support_resistance.py; the persistence/shadow tests run the real
record_markets, performance and scan-loop code. Trendline behaviour must be
unaffected throughout.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g  # noqa: E402
import sr_fixtures as f  # noqa: E402

import main  # noqa: E402
import observations  # noqa: E402
import strategies  # noqa: E402
from outcomes import resolve_due_market_outcomes  # noqa: E402
from performance import performance_report  # noqa: E402
from strategies import MarketInput, SupportResistanceStrategy  # noqa: E402
from strategies import support_resistance as sr  # noqa: E402
from test_market_data import IC_MARKETS, FakeBroker, run_scan  # noqa: E402
from test_strategy_isolation import IsolationTestCase, Store, market  # noqa: E402

EVIDENCE_KEYS = {"method", "levels_found", "tolerance", "atr", "timeframes_used", "unavailable_timeframes", "level",
                 "family", "distance_atr_h1", "touch", "rejection", "confirmation", "plan"}
LEVEL_KEYS = {"type", "price", "zone_low", "zone_high", "reactions", "strength", "reactions_by_timeframe",
              "higher_timeframe_reactions", "higher_timeframe_confluence", "role_reversal", "last_reaction_time"}


def evaluate(m15, h1=None, **extra):
    bars = {"M15": m15, "H1": h1 if h1 is not None else f.range_h1(), **extra}
    return SupportResistanceStrategy().evaluate(MarketInput("SYN", [dict(b) for b in m15], bars=bars))


def with_htf(m15):
    return evaluate(m15, H4=f.htf_bars(14400.0), D1=f.htf_bars(86400.0))


class LevelTests(unittest.TestCase):
    def test_range_produces_one_support_and_one_resistance_level(self):
        m15, h1 = f.range_m15(), f.range_h1()
        tolerance = sr.TOLERANCE_ATR_H1 * sr._atr(h1)
        levels = sr.find_levels({"M15": m15, "H1": h1}, tolerance)
        self.assertEqual(len(levels), 2)
        support, resistance = levels
        self.assertLess(abs(support["price"] - 99.8), tolerance)
        self.assertLess(abs(resistance["price"] - 110.2), tolerance)
        for level in levels:
            self.assertGreaterEqual(level["reactions"], sr.MIN_REACTIONS)
            self.assertGreaterEqual(level["strength"], sr.MIN_STRENGTH)
            self.assertGreaterEqual(level["zone_high"] - level["zone_low"], tolerance - 1e-9)
            self.assertEqual(set(level["reactions_by_timeframe"]), {"M15", "H1"})

    def test_swing_pivots_match_the_scanner_rule(self):
        from scanner import _swings
        for rows in (f.range_m15(), f.range_h1(), f.support_ending("bounce"), f.break_retest()[0], *[fx["rows"] for fx in g.load_fixtures()]):
            for strength in (2, 3):
                self.assertEqual(sr.swing_pivots(rows, strength), _swings(rows, strength))

    def test_clustering_follows_the_atr_tolerance(self):
        m15, h1 = f.range_m15(), f.range_h1()
        # Perturbed swing lows within the tolerance still form one level.
        noisy = [{**bar, "low": bar["low"] + (0.15 if index % 40 == 11 else 0.0)} for index, bar in enumerate(m15)]
        tolerance = sr.TOLERANCE_ATR_H1 * sr._atr(h1)
        self.assertEqual(len(sr.find_levels({"M15": noisy, "H1": h1}, tolerance)), 2)
        # A far smaller tolerance splits reactions that no longer lie together.
        self.assertGreater(len(sr.find_levels({"M15": noisy, "H1": h1}, tolerance / 50)), 2)

    def test_single_or_weak_reactions_are_not_levels(self):
        one_swing = f.bars(f.path((100.0, 0), (90.0, 20), (100.0, 20), (95.0, 20)), 0.2, f.M15_SECONDS)
        tolerance = 0.5
        self.assertEqual(sr.find_levels({"M15": one_swing}, tolerance), [], "one M15 reaction is not a level")

    def test_two_m15_reactions_need_higher_timeframe_confluence(self):
        two_lows = f.bars(f.path((100.0, 0), (90.0, 10), (100.0, 10), (90.0, 10), (100.0, 10)), 0.2, f.M15_SECONDS)
        one_low = f.bars(f.path((100.0, 0), (90.0, 10), (100.0, 10)), 0.2, f.M15_SECONDS)
        h4_low = f.bars(f.path((100.0, 0), (90.0, 5), (100.0, 5)), 0.3, 14400.0)
        self.assertEqual(sr.find_levels({"M15": two_lows}, 1.0), [], "two M15 swings alone are not a level")
        confluence = sr.find_levels({"M15": one_low, "H4": h4_low}, 1.0)
        self.assertEqual(len(confluence), 1)
        self.assertEqual((confluence[0]["reactions"], confluence[0]["higher_timeframe_reactions"]), (2, 1))

    def test_rules_are_instrument_agnostic(self):
        base = evaluate(f.support_ending("bounce"))
        for factor in (1000.0, 0.01):          # BTC/index-like prices, FX-like prices
            with self.subTest(factor=factor):
                result = evaluate(f.scaled(f.support_ending("bounce"), factor), f.scaled(f.range_h1(), factor))
                self.assertEqual((result["state"], result["direction"], result["strategy_valid"], result["rr"]),
                                 (base["state"], base["direction"], base["strategy_valid"], base["rr"]))
                self.assertAlmostEqual(result["stop_loss"], base["stop_loss"] * factor, delta=abs(base["stop_loss"] * factor) * 1e-9)
                self.assertEqual(result["strategy_evidence"]["levels_found"], base["strategy_evidence"]["levels_found"])

    def test_higher_timeframes_add_evidence_but_are_not_required(self):
        plain, htf = evaluate(f.support_ending("bounce")), with_htf(f.support_ending("bounce"))
        self.assertTrue(plain["strategy_valid"] and htf["strategy_valid"])
        self.assertFalse(plain["strategy_evidence"]["level"]["higher_timeframe_confluence"])
        level = htf["strategy_evidence"]["level"]
        self.assertTrue(level["higher_timeframe_confluence"])
        self.assertEqual(set(level["reactions_by_timeframe"]), {"M15", "H1", "H4", "D1"})
        self.assertGreater(level["strength"], plain["strategy_evidence"]["level"]["strength"])
        self.assertEqual(plain["score_breakdown"]["higher_timeframe"], 0)
        self.assertEqual(htf["score_breakdown"]["higher_timeframe"], 20)
        self.assertEqual(htf["strategy_evidence"]["timeframes_used"], ["D1", "H1", "H4", "M15"])


class SetupTests(unittest.TestCase):
    def test_buy_from_support_after_confirmed_rejection(self):
        result = evaluate(f.support_ending("bounce"))
        self.assertEqual((result["state"], result["direction"], result["setup_family"], result["setup"]),
                         ("CONFIRMING", "LONG", "SR_BOUNCE", "Support bounce"))
        self.assertTrue(result["strategy_valid"])
        rules = result["strategy_evidence"]["confirmation"]["rules"]
        self.assertEqual(set(rules), set(sr.CONFIRMATION_RULES))
        self.assertTrue(all(rules.values()))
        self.assertEqual(result["strategy_evidence"]["level"]["type"], "SUPPORT")

    def test_sell_from_resistance_after_confirmed_rejection(self):
        result = evaluate(f.resistance_rejection())
        self.assertEqual((result["state"], result["direction"], result["setup_family"], result["setup"]),
                         ("CONFIRMING", "SHORT", "SR_BOUNCE", "Resistance rejection"))
        self.assertTrue(result["strategy_valid"])
        self.assertEqual(result["strategy_evidence"]["level"]["type"], "RESISTANCE")
        self.assertGreater(result["stop_loss"], result["entry"])
        self.assertLess(result["take_profit"], result["entry"])

    def test_nearness_alone_is_not_a_setup(self):
        approach = evaluate(f.support_ending("approach"))
        self.assertEqual((approach["state"], approach["strategy_valid"]), ("WATCHING", False))
        self.assertEqual((approach["entry"], approach["stop_loss"], approach["take_profit"]), (None, None, None))
        touched = evaluate(f.support_ending("no_rejection"))
        self.assertEqual((touched["state"], touched["strategy_valid"]), ("DEVELOPING", False))
        self.assertEqual(set(touched["strategy_evidence"]["confirmation"]["failed"]), {"rejection", "momentum"})
        weak = evaluate(f.support_ending("weak_close"))                  # momentum without a rejection candle
        self.assertEqual((weak["state"], weak["strategy_valid"]), ("DEVELOPING", False))
        self.assertTrue(weak["strategy_evidence"]["confirmation"]["rules"]["momentum"])
        self.assertIn("rejection", weak["strategy_evidence"]["confirmation"]["failed"])

    def test_touch_without_an_approach_is_not_a_test(self):
        result = evaluate(f.support_ending("chop"))
        self.assertEqual((result["state"], result["strategy_valid"]), ("WATCHING", False))
        touch = result["strategy_evidence"]["touch"]
        self.assertEqual((touch["touched"], touch["clean_test"]), (True, False))
        self.assertLess(touch["approach_atr_h1"], sr.TEST_DISTANCE_ATR_H1)
        self.assertGreaterEqual(evaluate(f.support_ending("bounce"))["strategy_evidence"]["touch"]["approach_atr_h1"], sr.TEST_DISTANCE_ATR_H1)

    def test_failed_rejection_is_no_setup(self):
        result = evaluate(f.support_ending("failed"))
        self.assertEqual((result["state"], result["direction"], result["strategy_valid"]), ("NO SETUP", None, False))
        self.assertIn("failed rejection", result["reason"])
        self.assertEqual(result["strategy_evidence"]["failed_level"]["type"], "SUPPORT")
        self.assertIsNone(evaluate(f.support_ending("approach"))["strategy_evidence"].get("failed_level"))

    def test_break_and_retest_of_former_resistance(self):
        m15, h1 = f.break_retest()
        result = evaluate(m15, h1)
        self.assertEqual((result["state"], result["direction"], result["setup_family"], result["setup"]),
                         ("CONFIRMING", "LONG", "SR_BREAK_RETEST", "Resistance break/retest"))
        self.assertTrue(result["strategy_valid"])
        self.assertTrue(result["strategy_evidence"]["level"]["role_reversal"])
        self.assertAlmostEqual(result["strategy_evidence"]["plan"]["target_level_price"], 120.2, delta=0.8)

    def test_entry_stop_target_and_r_follow_the_documented_plan(self):
        result = evaluate(f.support_ending("bounce"))
        evidence = result["strategy_evidence"]
        atr_m15 = evidence["atr"]["M15"]
        self.assertEqual(result["entry"], 101.6)                                           # current price
        self.assertAlmostEqual(result["stop_loss"], evidence["level"]["zone_low"] - sr.STOP_BUFFER_ATR_M15 * atr_m15)
        resistance = sr.find_levels({"M15": f.support_ending("bounce"), "H1": f.range_h1()}, evidence["tolerance"])[-1]
        self.assertAlmostEqual(result["take_profit"], resistance["zone_low"])                # near edge of the next level
        risk, reward = result["entry"] - result["stop_loss"], result["take_profit"] - result["entry"]
        self.assertEqual(result["rr"], round(reward / risk, 2))
        self.assertGreaterEqual(result["rr"], sr.MIN_RR)
        self.assertEqual(result["invalidation_hint"], result["stop_loss"])
        self.assertEqual(evidence["plan"], {"entry": result["entry"], "stop": result["stop_loss"], "target": result["take_profit"],
            "target_level_price": resistance["price"], "risk": risk, "reward": reward, "rr": result["rr"], "min_rr": sr.MIN_RR})

    def test_minimum_r_makes_an_otherwise_confirmed_setup_a_candidate_only(self):
        with mock.patch.object(sr, "MIN_RR", 5.0):
            result = evaluate(f.support_ending("bounce"))
        self.assertEqual((result["state"], result["strategy_valid"]), ("CONFIRMING", False))
        self.assertEqual(result["strategy_evidence"]["confirmation"]["failed"], ["min_rr"])

    def test_evidence_is_complete_and_serialisable(self):
        result = with_htf(f.support_ending("bounce"))
        evidence = result["strategy_evidence"]
        self.assertEqual(set(evidence), EVIDENCE_KEYS)
        self.assertEqual(set(evidence["level"]), LEVEL_KEYS)
        self.assertEqual(json.loads(json.dumps(result)), result)
        for key in ("state", "direction", "strategy_valid", "entry", "stop_loss", "take_profit", "invalidation_hint", "score", "score_breakdown"):
            self.assertIn(key, result)
        self.assertEqual(result["score"], min(100, sum(result["score_breakdown"].values())))

    def test_deterministic_and_does_not_mutate_input(self):
        m15 = f.support_ending("bounce")
        market_input = MarketInput("SYN", m15, bars={"M15": m15, "H1": f.range_h1()})
        before = copy.deepcopy(market_input)
        first, second = SupportResistanceStrategy().evaluate(market_input), SupportResistanceStrategy().evaluate(market_input)
        self.assertEqual(first, second)
        self.assertEqual(market_input, before)
        self.assertEqual(evaluate(f.range_m15(40))["state"], "NO SETUP")                    # insufficient history


def sr_market(payload: dict, symbol: str = "XAUUSD", price: float | None = None) -> dict:
    """The market dict main builds for a non-trendline strategy result."""
    last = payload.get("entry") or 100.0
    return {"symbol": symbol, "broker_symbol": symbol, "price": price if price is not None else last, "bid": last, "ask": last,
            "spread": 0.0, "change_pct": 0.0, **payload, "timeframe": "M15", "higher_timeframes": ["H1", "H4", "D1"],
            "strategy_id": "support_resistance", "strategy_version": payload["strategy_version"], "strategy_mode": "SHADOW",
            "time_provenance": {"source_time_basis": "UTC", "timezone_normalization_status": "VERIFIED"},
            "source_timestamp": g.BASE_NOW.isoformat()}


class ShadowPersistenceTests(IsolationTestCase):
    def test_registry_runs_sr_in_shadow_mode_with_its_own_identity(self):
        self.assertEqual(strategies.REGISTRY.mode("support_resistance"), "SHADOW")
        self.assertEqual(strategies.REGISTRY.live(), ["trendline"])
        self.assertEqual((SupportResistanceStrategy.strategy_id, SupportResistanceStrategy.version), ("support_resistance", "sr-levels-v1"))
        self.assertNotEqual(SupportResistanceStrategy.version, strategies.TrendlineStrategy.version)
        m15 = f.support_ending("bounce")
        results = strategies.REGISTRY.evaluate(MarketInput("SYN", m15, higher_rows=f.range_h1(), bars={"M15": m15, "H1": f.range_h1()}))
        self.assertEqual({sid: r.mode for sid, r in results.items()}, {"trendline": "LIVE", "support_resistance": "SHADOW", "trend_momentum": "SHADOW"})

    def test_lifecycle_evidence_and_single_confirmation(self):
        developing = evaluate(f.support_ending("no_rejection"))
        confirmed = evaluate(f.support_ending("bounce"))
        failed = evaluate(f.support_ending("failed"))
        first = self.store.scan(sr_market(developing))[0]
        for _ in range(2):
            again = self.store.scan(sr_market(confirmed))[0]
            self.assertEqual(again["setup_id"], first["setup_id"])
        closing = self.store.scan(sr_market(failed, price=98.6))[0]
        events = [(e["from_state"], e["to_state"], e["reason_code"]) for e in self.store.events_for(first["setup_id"])]
        self.assertEqual(events, [(None, "DEVELOPING", "FIRST_DETECTION"), ("DEVELOPING", "CONFIRMED", "SCANNER_STATE_CHANGED"),
                                  ("CONFIRMED", "ACTIVE", "SCANNER_STATE_CHANGED"), ("ACTIVE", "INVALIDATED", "INVALIDATION_PRICE_CROSSED")])
        self.assertNotIn("setup_id", closing, "a failed rejection opens nothing")
        snapshots = [s for s in self.store.records("setup_observations.jsonl") if s["setup_id"] == first["setup_id"]]
        for snapshot in snapshots:
            self.assertEqual((snapshot["strategy_id"], snapshot["strategy_version"], snapshot.get("shadow")),
                             ("support_resistance", "sr-levels-v1", True))
            self.assertEqual(snapshot["episode_identity"]["strategy_id"], "support_resistance")
        self.assertEqual(snapshots[-1]["strategy_evidence"], json.loads(json.dumps(confirmed["strategy_evidence"])))
        self.assertEqual((snapshots[-1]["proposed_entry"], snapshots[-1]["proposed_stop_loss"], snapshots[-1]["proposed_take_profit"]),
                         (confirmed["entry"], confirmed["stop_loss"], confirmed["take_profit"]))
        confirmations = self.store.records("setup_confirmations.jsonl")
        self.assertEqual([(c["setup_id"], c["strategy_id"], c["strategy_version"], c.get("shadow")) for c in confirmations],
                         [(first["setup_id"], "support_resistance", "sr-levels-v1", True)])

    def test_coexists_with_trendline_in_either_direction_and_never_suppresses_it(self):
        sell = evaluate(f.resistance_rejection())
        buy = evaluate(f.support_ending("bounce"))
        for trend_direction, sr_payload in (("LONG", buy), ("LONG", sell), ("SHORT", sell), ("SHORT", buy)):
            with self.subTest(trendline=trend_direction, sr=sr_payload["direction"]):
                store = Store()
                try:
                    rounds = [store.scan(market(trend_direction, symbol="GER40", price=2650.0), sr_market(sr_payload, "GER40"))
                              for _ in range(3)]
                    trend_ids = {batch[0]["setup_id"] for batch in rounds}
                    sr_ids = {batch[1]["setup_id"] for batch in rounds}
                    self.assertEqual((len(trend_ids), len(sr_ids)), (1, 1))
                    self.assertFalse(trend_ids & sr_ids)
                    for setup_id in trend_ids | sr_ids:
                        self.assertFalse([e for e in store.events_for(setup_id) if e["to_state"] in {"INVALIDATED", "EXPIRED"}])
                    # Close the S/R episode by price; the trendline episode continues and is not suppressed.
                    store.scan(sr_market(evaluate(f.support_ending("failed")), "GER40", price=0.0 if sr_payload is buy else 10**6))
                    self.assertTrue([e for e in store.events_for(sr_ids.pop()) if e["to_state"] == "INVALIDATED"])
                    fresh = store.scan(market(trend_direction, symbol="GER40", price=2650.0))[0]
                    self.assertFalse(fresh.get("episode_suppressed"))
                    self.assertIn(fresh["setup_id"], trend_ids)
                finally:
                    store.close()

    def test_shadow_episodes_and_confirmations_stay_out_of_live_views(self):
        self.store.scan(market("LONG", state="CONFIRMING", valid=True, invalidation=2600.0), sr_market(evaluate(f.support_ending("bounce"))))
        with g.isolated_store(observations, self.store.root):
            live = observations.setup_episodes("all", 100)
            review = observations.setup_episodes("all", 100, include_shadow=True)
            api_live = main.setup_episode_feed(bucket="all", limit=100)
            api_review = main.setup_episode_feed(bucket="all", limit=100, include_shadow=True)
        self.assertEqual({row["strategy_id"] for row in live}, {"trendline"})
        self.assertEqual({row["strategy_id"] for row in review}, {"trendline", "support_resistance"})
        self.assertEqual({r["strategy_id"] for b in ("current", "confirmed", "closed") for r in api_live[b]}, {"trendline"})
        self.assertIn("support_resistance", {r["strategy_id"] for b in ("current", "confirmed", "closed") for r in api_review[b]})
        confirmations = self.store.records("setup_confirmations.jsonl")
        self.assertEqual(sorted((c["strategy_id"], c.get("shadow", False)) for c in confirmations),
                         [("support_resistance", True), ("trendline", False)])
        with g.isolated_store(observations, self.store.root):
            snapshots = observations.performance_observations()
        report = performance_report(confirmations, [], snapshots, report_date=g.BASE_NOW.date().isoformat(), timezone_name="UTC")
        day = report["daily"][0]
        # The setups list feeds live confirmation alerts: live strategies only.
        self.assertEqual([s["strategy_id"] for s in day["setups"]], ["trendline"])
        self.assertEqual(day["confirmed"], 1)
        self.assertEqual(set(day["by_strategy"]), {"trendline", "support_resistance"})
        self.assertEqual(day["shadow_strategies"], ["support_resistance"])
        self.assertEqual(report["summary"]["shadow_strategies"], ["support_resistance"])
        self.assertEqual(day["watchlist"], 0, "shadow setups are not on the live watchlist")

    def test_outcomes_are_tracked_and_grouped_by_strategy(self):
        payload = evaluate(f.support_ending("bounce"))
        self.store.scan(sr_market(payload))
        confirmations = self.store.records("setup_confirmations.jsonl")
        snapshots = {s["observation_id"]: s for s in self.store.records("setup_observations.jsonl")}
        base = g.BASE_NOW.timestamp() + 60
        path = [101.6 + 0.8 * i for i in range(30)]                          # rallies through the target
        bars = {"XAUUSD": [{"time": base + i * 900, "open": p, "high": p + 0.3, "low": p - 0.3, "close": p} for i, p in enumerate(path)]}
        outcomes = resolve_due_market_outcomes(confirmations, snapshots, bars, [], ("1h", "4h", "24h"), now=g.BASE_NOW + timedelta(days=2))
        labels = {o["horizon"]: o["label"] for o in outcomes if o["setup_id"] == confirmations[0]["setup_id"]}
        self.assertEqual(labels["4h"], "WIN")
        report = performance_report(confirmations, outcomes, [], report_date=g.BASE_NOW.date().isoformat(), timezone_name="UTC")
        day = report["daily"][0]
        self.assertEqual(day["by_strategy"]["support_resistance"]["win"], 1)
        self.assertEqual((day["wins"], day["confirmed"]), (0, 0), "shadow results never enter the live headline")


class ScanLoopShadowTests(unittest.TestCase):
    def test_shadow_sr_in_the_scan_loop_leaves_trendline_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline, baseline_files = run_scan(FakeBroker(IC_MARKETS), g.trendline_only_registry(), root=Path(tmp) / "a")
            markets, files = run_scan(FakeBroker(IC_MARKETS), strategies.build_default_registry(), root=Path(tmp) / "b")
        strip = lambda rows: [{k: v for k, v in m.items() if k != "strategies"} for m in rows]  # noqa: E731
        self.assertEqual(g.canonical(strip(markets)), g.canonical(strip(baseline)), "top-level markets are the trendline result")
        for market_row in markets:
            modes = {entry["strategy_id"]: entry["mode"] for entry in market_row["strategies"]}
            self.assertEqual(modes, {"trendline": "LIVE", "support_resistance": "SHADOW", "trend_momentum": "SHADOW"})
        lines = files["setup_observations.jsonl"].splitlines(keepends=True)
        trend = [line for line in lines if json.loads(line)["strategy_id"] == "trendline"]
        self.assertEqual(b"".join(trend), baseline_files["setup_observations.jsonl"], "trendline records byte-identical")
        shadow = [json.loads(line) for line in lines if json.loads(line)["strategy_id"] == "support_resistance"]
        self.assertTrue(all(row.get("shadow") is True for row in shadow))
        for line in files.get("setup_confirmations.jsonl", b"").splitlines():
            event = json.loads(line)
            self.assertEqual(event.get("shadow") is True, event["strategy_id"] == "support_resistance")


if __name__ == "__main__":
    unittest.main()
