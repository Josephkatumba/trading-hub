"""V7: market regimes, SMC v2 target research variant, advisory allocation, participation flags,
diversification and coverage of every registered strategy. Synthetic data only (no MT5)."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import market_regime  # noqa: E402
from strategies import REGISTRY  # noqa: E402
from strategies import smc  # noqa: E402
from strategy_bank import allocation, engine, rules  # noqa: E402
from research import participation as part  # noqa: E402


def _bars(n: int, start: float, step: float, tf_seconds: int, drift: float = 0.0, seed: int = 1) -> list[dict]:
    rng = np.random.default_rng(seed)
    price, out = 100.0, []
    for i in range(n):
        move = drift + rng.normal(0, 0.3)
        o = price
        c = price + move
        h, l = max(o, c) + abs(rng.normal(0, 0.15)), min(o, c) - abs(rng.normal(0, 0.15))
        out.append({"time": start + i * tf_seconds, "utc": start + i * tf_seconds, "open": o, "high": h, "low": l, "close": c,
                    "tick_volume": 100, "spread": 0.01})
        price = c
    return out


def _ctx(h1: list[dict], h4: list[dict]) -> rules.Ctx:
    return rules.Ctx("TEST", {"H1": h1, "H4": h4})


class RegimeTests(unittest.TestCase):
    def setUp(self):
        start = 1_700_000_000.0
        self.h1 = _bars(700, start, 3600, 3600, drift=0.02)
        self.h4 = _bars(400, start - 200 * 14400, 14400, 14400, drift=0.05, seed=2)

    def test_labels_are_known_regimes_and_unknown_before_history(self):
        labels = market_regime.label_array(_ctx(self.h1, self.h4))
        self.assertTrue(all(x == "UNKNOWN" for x in labels[:market_regime.MIN_INDEX]))
        self.assertTrue(set(labels[market_regime.MIN_INDEX:]) <= set(market_regime.REGIMES))

    def test_classification_is_causal(self):
        """Appending future bars must not change the regime already known at an earlier bar."""
        full = market_regime.label_array(_ctx(self.h1, self.h4))
        cut = 500
        h4_cut = [b for b in self.h4 if b["utc"] + 14400 <= self.h1[cut - 1]["utc"] + 3600]
        prefix = market_regime.label_array(_ctx(self.h1[:cut], h4_cut))
        self.assertEqual(list(prefix[:cut]), list(full[:cut]))

    def test_tag_is_informational(self):
        ctx = _ctx(self.h1, self.h4)
        t = market_regime.tag(ctx, "bollinger_reversion", self.h1[-1]["utc"] + 3600)
        self.assertEqual(t["family"], "Mean Reversion")
        self.assertIn(t["regime"], market_regime.REGIMES + ("UNKNOWN",))
        self.assertEqual(t["in_design_regime"], t["regime"] in market_regime.SUITABILITY["Mean Reversion"])

    def test_every_family_has_designed_regimes(self):
        for family, regimes in market_regime.SUITABILITY.items():
            self.assertTrue(regimes, family)
            self.assertTrue(set(regimes) <= set(market_regime.REGIMES), family)


class CoverageTests(unittest.TestCase):
    def test_every_registered_strategy_has_a_methodology_family(self):
        """The participation report classifies every strategy the system runs: the live registry and
        every bank spec (core, admitted expansion, ICT, upgrades)."""
        rules.load_expansion()
        keys = set(REGISTRY.registered()) | {s["key"] for s in rules.SPECS if s["status"] != rules.LINKED}
        missing = sorted(k for k in keys if k not in market_regime.STRATEGY_FAMILY)
        self.assertEqual(missing, [])
        for key, (family, concepts) in market_regime.STRATEGY_FAMILY.items():
            self.assertIn(family, market_regime.SUITABILITY, key)
            self.assertTrue(set(concepts) <= set(market_regime.SUITABILITY), key)

    def test_production_smc_version_is_unchanged(self):
        self.assertEqual(REGISTRY.get("smc").version, "smc-confluence-v1")
        self.assertNotIn("smc-confluence-v2", [d["version"] for d in REGISTRY.describe()])


class SmcTargetTests(unittest.TestCase):
    def _h1(self):
        # swing high at 3 (110) is later traded through by bar 9 (112); swing high at 12 (115) is untaken.
        highs = [100, 104, 106, 110, 106, 104, 103, 105, 108, 112, 108, 109, 115, 109, 107, 105, 104]
        return [{"time": i, "high": h, "low": h - 3, "open": h - 1, "close": h - 2} for i, h in enumerate(highs)]

    def test_v1_targets_nearest_swing_v2_only_untaken_liquidity(self):
        h1 = self._h1()
        self.assertEqual(smc.liquidity_target(h1, 105.0, True, smc.STRATEGY_VERSION), 110)
        self.assertEqual(smc.liquidity_target(h1, 105.0, True, smc.V2_VERSION), 115)

    def test_untaken_keeps_equal_highs(self):
        rows = [{"high": h, "low": h - 1} for h in (1, 5, 1, 1, 5, 1)]
        self.assertEqual(smc.untaken(rows, [(1, 5.0)], True), [(1, 5.0)])

    def test_unknown_version_is_rejected(self):
        with self.assertRaises(ValueError):
            smc.analyze_smc(mock.Mock(bars={}, rows=[], higher_rows=[], unavailable_timeframes={}), "smc-x")


class AllocationTests(unittest.TestCase):
    def _ev(self, tier, failing=()):
        names = ("sample", "out_of_sample", "significance", "costs", "walk_forward")
        return {"tier": tier, "checks": {n: {"pass": n not in failing} for n in names}}

    def test_classes_follow_evidence_never_volume(self):
        pol = {**allocation.DEFAULT_POLICY, "production_approved": ["a"]}
        good_fwd = {"resolved": 80, "expectancy_r": 0.2, "profit_factor": 1.4}
        self.assertEqual(allocation.classify(self._ev("SUSPENDED", ("costs",)), None, "x", pol)["class"], "RESEARCH")
        self.assertTrue(allocation.classify(self._ev("SUSPENDED", ("costs",)), None, "x", pol)["suspension_recommended"])
        self.assertEqual(allocation.classify(self._ev("EXPERIMENTAL", ("costs",)), {"resolved": 5000}, "x", pol)["class"], "RESEARCH")
        self.assertEqual(allocation.classify(self._ev("RESEARCH", ("significance",)), None, "x", pol)["class"], "EXPERIMENTAL")
        self.assertEqual(allocation.classify(self._ev("VALIDATED"), None, "a", pol)["class"], "VALIDATED")
        self.assertEqual(allocation.classify(self._ev("VALIDATED"), good_fwd, "b", pol)["class"], "VALIDATED")   # not approved
        self.assertEqual(allocation.classify(self._ev("VALIDATED"), good_fwd, "a", pol)["class"], "PRODUCTION")

    def test_weights_zero_below_validated_and_shared_in_clusters(self):
        rows = [{"key": "a", "class": "VALIDATED", "ci_lower": 0.1}, {"key": "b", "class": "VALIDATED", "ci_lower": 0.1},
                {"key": "c", "class": "VALIDATED", "ci_lower": 0.2}, {"key": "d", "class": "EXPERIMENTAL", "ci_lower": 0.5}]
        w = allocation.weights(rows, {"a": 0, "b": 0, "c": 1, "d": 2}, {**allocation.DEFAULT_POLICY, "max_weight_per_strategy": 1.0})
        self.assertEqual(w["d"], 0.0)
        self.assertAlmostEqual(w["a"] + w["b"], w["c"] / 2, places=3)          # a and b share one cluster's allocation
        self.assertEqual(allocation.weights([{"key": "x", "class": "RESEARCH", "ci_lower": 1.0}]), {"x": 0.0})


class FlagTests(unittest.TestCase):
    def _row(self, key, system, confirmed, setups=None, rate=None, top_share=0.0, hist=None):
        return {"key": key, "system": system, "scanned": True, "live": {"confirmed": confirmed},
                "funnel": {"setups": setups, "confirmation_rate": rate, "top_rejection": "min_rr", "top_rejection_share": top_share},
                "historical": hist}

    def test_flags(self):
        neg = {"trades_per_month": 90, "expectancy_r": -0.2, "expectancy_ci95": [-0.3, -0.1], "evidence": {"tier": "SUSPENDED"}}
        pos = {"trades_per_month": 5, "expectancy_r": 0.05, "expectancy_ci95": [-0.05, 0.15], "evidence": {"tier": "RESEARCH"},
               "development_expectancy": 0.04, "test_expectancy": 0.06, "trades": 400}
        rows = [self._row("tl", "LIVE_SCANNER", 70, hist=neg), self._row("sr", "LIVE_SCANNER", 25, 900, 0.01, 0.9),
                self._row("tm", "LIVE_SCANNER", 3), self._row("sm", "LIVE_SCANNER", 0, hist=pos)]
        part.classify_rows(rows)
        f = {r["key"]: set(r["flags"]) for r in rows}
        self.assertIn("DOMINANT", f["tl"])
        self.assertIn("HIGH_VOLUME_LOW_QUALITY", f["tl"])
        self.assertIn("EXCESSIVE_FILTERING", f["sr"])
        self.assertIn("UNDERREPRESENTED", f["tm"])
        self.assertIn("INACTIVE", f["sm"])
        self.assertIn("PROMISING", f["sm"])
        self.assertNotIn("PROMISING", f["tl"])       # volume never makes a strategy promising


class DiversificationTests(unittest.TestCase):
    def test_duplicate_strategies_cluster_and_independent_ones_do_not(self):
        rng = np.random.default_rng(3)
        base = [{"utc": 1.7e9 + i * 86400, "symbol": "XAUUSD", "direction": "LONG" if i % 2 else "SHORT", "index": i * 96,
                 "exit_index": i * 96 + 10, "r": float(rng.choice([-1.0, 2.0]))} for i in range(60)]
        other = [{**t, "symbol": "EURUSD", "index": t["index"] + 40, "exit_index": t["index"] + 45,
                  "r": float(rng.choice([-1.0, 2.0]))} for t in base]
        trades = {"a": base, "b": [dict(t) for t in base], "c": other}
        d = part.diversification(trades, {}, ["a", "b", "c"], min_trades=30)
        pair = {(p["a"], p["b"]): p for p in d["pairs"]}
        self.assertEqual(pair[("a", "b")]["overlap_a"], 1.0)
        self.assertAlmostEqual(pair[("a", "b")]["outcome_corr"], 1.0, places=6)
        self.assertEqual(pair[("a", "c")]["overlap_a"], 0.0)
        self.assertIn(["a", "b"], [sorted(c) for c in d["clusters"]])
        self.assertTrue(1.0 <= d["effective_independent_sources"] <= 3.0)


class BankRegimeTagTests(unittest.TestCase):
    def test_regime_tag_never_blocks_a_signal(self):
        start = 1_700_000_000.0
        h1 = _bars(450, start, 3600, 3600)
        ctx = rules.Ctx("XAUUSD", {"H1": h1, "H4": _bars(300, start - 100 * 14400, 14400, 14400, seed=4)})
        spec = {"key": "breakout", "name": "Breakout", "status": rules.EXPERIMENTAL, "timeframe": "H1", "min_rr": 1.5}
        i = len(h1) - 1
        close = float(ctx.a["H1"]["close"][i])
        quote = {"bid": close, "ask": close + 0.001, "tick_age_seconds": 0.0}
        d = rules.Decision("LONG", stop_atr=1.0, target_r=2.0)
        with mock.patch.object(market_regime, "tag", side_effect=RuntimeError("boom")):
            signal, reason = engine.confirm(spec, d, ctx, i, quote, ctx.close_utc("H1", i), check_freshness=False)
        self.assertEqual(reason, "")
        self.assertIsNone(signal["regime"])
        signal, _ = engine.confirm(spec, d, ctx, i, quote, ctx.close_utc("H1", i), check_freshness=False)
        self.assertIn(signal["regime"]["regime"], market_regime.REGIMES + ("UNKNOWN",))


class StatsTests(unittest.TestCase):
    def test_perf(self):
        p = part.perf([1.0, -1.0, 2.0, -1.0], months=2.0)
        self.assertEqual(p["trades"], 4)
        self.assertAlmostEqual(p["expectancy_r"], 0.25)
        self.assertAlmostEqual(p["profit_factor"], 1.5)
        self.assertEqual(p["max_drawdown_r"], 1.0)
        self.assertEqual(p["trades_per_month"], 2.0)
        self.assertTrue(math.isnan(float("nan")) or p["expectancy_ci95"][0] <= 0.25 <= p["expectancy_ci95"][1])


if __name__ == "__main__":
    unittest.main()
