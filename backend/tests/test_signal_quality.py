"""Signal quality engine: causality, scorecard fitting and grading, lifecycle, live gate modes, walk-forward mechanics."""
from __future__ import annotations

import math
import os
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from signal_quality import features as feat
from signal_quality import lifecycle, live, regime
from signal_quality.model import MIN_EVIDENCE, QualityModel, form_bucket, regime_cap
from strategy_bank import engine, indicators as ind, rules
from test_strategy_bank import frames


def ctx_for(f, symbol="EURUSD"):
    return rules.Ctx(symbol, f)


def truncated(f, at_utc):
    """Only bars CLOSED by at_utc, per timeframe."""
    return {tf: [b for b in bars if b["utc"] + rules.TF_SECONDS[tf] <= at_utc] for tf, bars in f.items()}


class CausalityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = frames(days=260, seed=11)
        cls.full = ctx_for(cls.f)

    def test_adx_uses_only_past_bars(self):
        a = self.full.a["H1"]
        full, _, _ = ind.adx(a["high"], a["low"], a["close"])
        for cut in (120, 600, len(a["close"]) - 1):
            part, _, _ = ind.adx(a["high"][:cut + 1], a["low"][:cut + 1], a["close"][:cut + 1])
            self.assertTrue(math.isclose(part[cut], full[cut], rel_tol=1e-12) or (np.isnan(part[cut]) and np.isnan(full[cut])))

    def test_regime_and_features_identical_with_future_bars_removed(self):
        h1 = self.f["H1"]
        checked = 0
        for k in range(300, len(h1) - 5, 397):
            at = h1[k]["utc"] + 3600 + 60
            entry = h1[k]["close"]
            stop, target = entry - 0.002, entry + 0.004
            short = ctx_for(truncated(self.f, at))
            self.assertEqual(regime.classify(self.full, at), regime.classify(short, at))
            a = feat.compute(self.full, at, "ema_pullback", "LONG", entry, stop, target)["features"]
            b = feat.compute(short, at, "ema_pullback", "LONG", entry, stop, target)["features"]
            self.assertEqual(a, b)
            checked += 1
        self.assertGreater(checked, 5)

    def test_injected_future_shock_does_not_change_past_regime(self):
        h1 = self.f["H1"]
        at = h1[900]["utc"] + 3600
        before = regime.classify(self.full, at)
        shocked = {tf: [dict(b) for b in bars] for tf, bars in self.f.items()}
        for tf, bars in shocked.items():
            for b in bars:
                if b["utc"] >= at:
                    b["high"] *= 1.05
                    b["close"] *= 1.04
        self.assertEqual(before, regime.classify(ctx_for(shocked), at))

    def test_regime_labels_and_direction_relative_features(self):
        h1 = self.f["H1"]
        at = h1[1000]["utc"] + 3600
        r = regime.classify(self.full, at)
        self.assertIn(r["regime"], regime.REGIMES)
        e = h1[1000]["close"]
        long = feat.compute(self.full, at, "donchian", "LONG", e, e - 0.002, e + 0.004)["features"]
        short = feat.compute(self.full, at, "donchian", "SHORT", e, e + 0.002, e - 0.004)["features"]
        flip = {"with": "against", "against": "with", "neutral": "neutral", "mixed": "mixed", "unknown": "unknown"}
        for name in ("htf_d1", "di", "structure"):
            self.assertEqual(flip[long[name]], short[name], name)
        self.assertEqual(long["family"], "breakout")
        self.assertEqual(long["session"], feat.session(at))


class ModelTests(unittest.TestCase):
    def rows(self, n=6000, seed=3):
        rng = random.Random(seed)
        out = []
        for _ in range(n):
            htf = rng.choice(["with", "against"])
            noise = rng.choice(["x", "y", "z"])
            win = rng.random() < (0.45 if htf == "with" else 0.25)
            out.append(({"strategy": "s", "htf_h4": htf, "rsi": noise, "family": "breakout", "regime": "TRENDING"}, 2.0 if win else -1.0))
        return out

    def test_recovers_a_real_effect_and_shrinks_noise(self):
        m = QualityModel.fit(self.rows(), ("strategy", "htf_h4", "rsi"))
        self.assertGreater(m.predict({"strategy": "s", "htf_h4": "with", "rsi": "x"}),
                           m.predict({"strategy": "s", "htf_h4": "against", "rsi": "x"}) + 0.4)
        self.assertLess(max(abs(v) for v in m.effects["rsi"].values()), 0.08)

    def test_rare_bucket_is_shrunk_towards_zero(self):
        rows = self.rows(4000) + [({"strategy": "s", "htf_h4": "with", "rsi": "rare"}, 2.0)] * 5
        m = QualityModel.fit(rows, ("strategy", "htf_h4", "rsi"))
        self.assertLess(m.effects["rsi"]["rare"], 0.06)        # 5 lucky trades cannot create an A+ bucket

    def test_grades_thresholds_and_caps(self):
        m = QualityModel(base=0.2, effects={"htf_h4": {"with": 0.2, "against": -0.4}}, strategy_trades={"s": MIN_EVIDENCE + 1, "thin": 10})
        g = lambda **f: m.grade({"strategy": "s", "family": "breakout", "regime": "TRENDING", **f})
        self.assertEqual(g(htf_h4="with")["grade"], "A+")
        self.assertTrue(g(htf_h4="with")["confirmable"])
        self.assertEqual(g(htf_h4="against")["grade"], "REJECTED")
        self.assertEqual(g(htf_h4="neutral")["grade"], "A")
        capped = m.grade({"strategy": "s", "family": "trend", "regime": "RANGING", "htf_h4": "with"})
        self.assertEqual(capped["grade"], "C")
        self.assertFalse(capped["confirmable"])
        self.assertTrue(capped["caps"])
        self.assertEqual(m.grade({"strategy": "s", "family": "trend", "regime": "RANGING", "htf_h4": "with"}, apply_caps=False)["grade"], "A+")
        thin = m.grade({"strategy": "thin", "family": "breakout", "regime": "TRENDING", "htf_h4": "with"})
        self.assertEqual(thin["grade"], "B")

    def test_regime_compatibility_rules(self):
        self.assertEqual(regime_cap({"family": "reversion", "regime": "TRENDING", "regime_trend": "against"})[0], "C")
        self.assertIsNone(regime_cap({"family": "reversion", "regime": "TRENDING", "regime_trend": "with"})[0])
        self.assertIsNone(regime_cap({"family": "breakout", "regime": "RANGING"})[0])

    def test_json_roundtrip(self):
        m = QualityModel.fit(self.rows(800), ("strategy", "htf_h4"), exits={"s": "t1.5"})
        with tempfile.TemporaryDirectory() as tmp:
            path = m.save(Path(tmp) / "m.json")
            back = QualityModel.load(path)
        f = {"strategy": "s", "htf_h4": "with"}
        self.assertAlmostEqual(m.predict(f), back.predict(f))
        self.assertEqual(back.exits, {"s": "t1.5"})

    def test_form_bucket(self):
        self.assertEqual(form_bucket([1.0] * 5), "insufficient")
        self.assertEqual(form_bucket([-1.0] * 30), "<-0.2")
        self.assertEqual(form_bucket([0.5] * 30), ">=0.2")


class LifecycleTests(unittest.TestCase):
    def test_only_a_grades_reach_confirmed(self):
        self.assertEqual(lifecycle.after_rules({"grade": "A", "expected_r": 0.2, "confirmable": True})["stage"], "CONFIRMED")
        no = lifecycle.after_rules({"grade": "B", "expected_r": 0.07, "confirmable": False, "caps": []})
        self.assertEqual((no["stage"], no["decision"]), ("NO_TRADE", "NO TRADE"))
        self.assertEqual(lifecycle.after_rules(None)["stage"], "CONFIRMING")

    def test_stage_of_stored_signals(self):
        self.assertEqual(lifecycle.stage_of({"outcome_status": "PENDING"}), "ACTIVE")
        self.assertEqual(lifecycle.stage_of({"outcome_status": "STOP_HIT"}), "RESOLVED")
        self.assertEqual(lifecycle.stage_of({"outcome_status": "PENDING", "quality": {"stage": "NO_TRADE"}}), "NO_TRADE")
        self.assertEqual(lifecycle.stage_of({"outcome_status": "PENDING", "quality": {"stage": "CONFIRMED"}}), "ACTIVE")


class LiveGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = engine.BankStore(Path(self.tmp.name))
        self.ctx = ctx_for(frames(days=200, seed=5))

    def tearDown(self):
        self.tmp.cleanup()

    def _signal(self, sid="bank_1"):
        h1 = self.ctx.a["H1"]
        i = len(h1["close"]) - 1
        e = float(h1["close"][i])
        from datetime import datetime, timezone
        return {"signal_id": sid, "strategy_key": "donchian", "strategy_name": "Donchian", "symbol": "EURUSD", "direction": "LONG",
                "confirmed_at": datetime.fromtimestamp(self.ctx.close_utc("H1", i), timezone.utc).isoformat(),
                "entry": e, "stop_loss": e - 0.003, "take_profit": e + 0.006}

    def test_assess_grades_from_closed_bars(self):
        m = QualityModel(base=-0.2, effects={}, strategy_trades={"donchian": 5000})
        with mock.patch.dict(os.environ, {"TRADEDEN_QUALITY_GATE": "shadow"}):
            q = live.assess(self.ctx, self._signal(), [], m)
        self.assertEqual(q["grade"], "REJECTED")
        self.assertEqual(q["stage"], "NO_TRADE")
        self.assertEqual(q["mode"], "shadow")
        self.assertIn("regime", q["features"])
        with mock.patch.dict(os.environ, {"TRADEDEN_QUALITY_GATE": "off"}):
            self.assertIsNone(live.assess(self.ctx, self._signal(), [], m))

    def test_assess_never_raises(self):
        m = QualityModel(base=0.0)
        with mock.patch.dict(os.environ, {"TRADEDEN_QUALITY_GATE": "shadow"}):
            self.assertIsNone(live.assess(self.ctx, {"signal_id": "x"}, [], m))

    def _scan(self, gate, base):
        bank = engine.Bank(self.store)
        h1 = self.ctx.a["H1"]
        i = len(h1["close"]) - 1
        spec = {"key": "donchian", "name": "Donchian", "n": 10, "status": rules.EXPERIMENTAL, "timeframe": "H1",
                "instruments": ("EURUSD",), "min_rr": 1.5, "decide": lambda ctx, j: rules.Decision("LONG", stop_atr=1.5, target_r=2.0) if j == i else None}
        quote = {"bid": float(h1["close"][i]), "ask": float(h1["close"][i]) + 0.00005, "tick_age_seconds": 1.0}
        m = QualityModel(base=base, effects={}, strategy_trades={"donchian": 5000})
        with mock.patch.dict(os.environ, {"TRADEDEN_QUALITY_GATE": gate}), \
                mock.patch.object(rules, "scanned", return_value=[spec]), mock.patch.object(live, "model", return_value=m):
            return bank.scan(self.ctx, quote, self.ctx.close_utc("H1", i) + 5, check_freshness=False)

    def test_enforce_records_no_trade_without_alert_or_blocking(self):
        new = self._scan("enforce", -0.5)
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["alert"], "no trade (quality gate)")
        self.assertEqual(self.store.opportunities, {})
        self.assertIsNone(self.store.open_signal("donchian", "EURUSD"))
        self.assertIn("NO_TRADE", new[0]["quality"]["stage"])

    def test_shadow_annotates_but_keeps_alerting(self):
        new = self._scan("shadow", -0.5)
        self.assertEqual(new[0]["alert"], "primary")
        self.assertEqual(new[0]["quality"]["grade"], "REJECTED")

    def test_enforce_lets_a_grades_through(self):
        new = self._scan("enforce", 0.5)
        self.assertEqual(new[0]["alert"], "primary")
        self.assertEqual(new[0]["quality"]["stage"], "CONFIRMED")


class WalkForwardMechanicsTests(unittest.TestCase):
    def row(self, utc, strategy="s", symbol="X", index=0, r=1.0, exit_index=5, exit_utc=None, **variants):
        out = {"base": {"r": r, "r2": r - 0.1, "outcome": "TP" if r > 0 else "SL", "exit_index": exit_index,
                        "entry_index": index, "exit_utc": exit_utc if exit_utc is not None else utc + 3600}}
        for k, v in variants.items():
            out[k.replace("_", ".")] = {"r": v, "r2": v, "outcome": "TP", "exit_index": exit_index, "entry_index": index, "exit_utc": utc + 3600}
        return {"utc": utc, "strategy": strategy, "symbol": symbol, "direction": "LONG", "index": index,
                "features": {"session": "LONDON", "regime": "RANGING"}, "outcomes": out}

    def test_filtered_signal_never_blocks_a_later_one(self):
        from research.quality_research import trade_list
        rows = [self.row(0, index=0, exit_index=10, r=-1), self.row(100, index=3, exit_index=8, r=2)]
        self.assertEqual(len(trade_list(rows, lambda r: "base")), 1)                    # second overlaps the first
        kept = trade_list(rows, lambda r: "base" if r["utc"] == 100 else None)
        self.assertEqual([t["r"] for t in kept], [2])

    def test_exit_choice_needs_sample_and_margin(self):
        from research import quality_research as q
        rows = [self.row(i, r=-1.0 if i % 2 else 1.0, t1_5=0.6) for i in range(q.MIN_EXIT_TRADES)]
        self.assertEqual(q.choose_exits(rows)["s"], "t1.5")
        self.assertEqual(q.choose_exits(rows[:50])["s"], "base")
        flat = [self.row(i, r=0.1, t1_5=0.11) for i in range(q.MIN_EXIT_TRADES)]
        self.assertEqual(q.choose_exits(flat)["s"], "base")

    def test_strategy_form_uses_only_exited_trades(self):
        from research.quality_research import add_strategy_form
        rows = [self.row(i * 10, r=-1.0, exit_utc=i * 10 + 5) for i in range(30)]
        late = self.row(10_000, r=1.0)
        rows.append(late)
        pending = [self.row(10_001 + i, r=5.0, exit_utc=99_999) for i in range(30)]   # not exited yet
        rows += pending
        add_strategy_form(rows)
        self.assertEqual(late["features"]["strategy_form"], "<-0.2")
        self.assertEqual(rows[5]["features"]["strategy_form"], "insufficient")


class AuditTests(unittest.TestCase):
    def test_outcome_stats(self):
        from research.signal_audit import outcome_stats, session_of
        rows = [{"t": str(i), "r": r} for i, r in enumerate([2.0, -1.0, -1.0, 2.0, -1.0])]
        s = outcome_stats(rows)
        self.assertEqual((s["wins"], s["losses"]), (2, 3))
        self.assertAlmostEqual(s["expectancy_r"], 0.2)
        self.assertAlmostEqual(s["profit_factor"], 4 / 3, places=3)
        self.assertEqual(s["max_drawdown_r"], 2.0)
        self.assertEqual(session_of("2026-11-18T13:00:00+00:00"), "LONDON_NY_OVERLAP")
        self.assertEqual(session_of("2026-11-18T03:00:00+00:00"), "ASIA")


if __name__ == "__main__":
    unittest.main()
