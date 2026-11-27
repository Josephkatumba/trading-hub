"""ICT family, strategy upgrades, confluence engine and evidence tiers."""
import random
import unittest
from datetime import datetime, timezone

from strategy_bank import ict, rules, upgrades, evidence_tiers
import confluence

M15 = 900
START = datetime(2026, 3, 2, tzinfo=timezone.utc).timestamp()      # a Monday


def walk(n=3200, seed=7, start=START, price=100.0):
    rnd = random.Random(seed)
    bars, p = [], price
    for k in range(n):
        t = start + k * M15
        hour = int(t // 3600 % 24)
        vol = 0.35 if hour < 7 else 0.7 if 12 <= hour < 17 else 0.5
        o = p
        c = o + rnd.gauss(0, vol)
        h = max(o, c) + abs(rnd.gauss(0, vol / 2))
        l = min(o, c) - abs(rnd.gauss(0, vol / 2))
        bars.append({"utc": t, "open": o, "high": h, "low": l, "close": c, "tick_volume": 100, "spread": 0.02})
        p = c
    return bars


def aggregate(m15, seconds):
    out, cur = [], None
    for b in m15:
        key = b["utc"] - b["utc"] % seconds
        if cur is None or cur["utc"] != key:
            cur = {"utc": key, "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"], "tick_volume": 0, "spread": b["spread"]}
            out.append(cur)
        cur["high"], cur["low"], cur["close"] = max(cur["high"], b["high"]), min(cur["low"], b["low"]), b["close"]
    return out


def frames(m15):
    return {"M15": m15, "H1": aggregate(m15, 3600), "H4": aggregate(m15, 14400), "D1": aggregate(m15, 86400)}


def truncated(m15, i):
    """Only what was known when M15 bar i closed: closed bars of every timeframe."""
    close_t = m15[i]["utc"] + M15
    fr = {"M15": m15[:i + 1]}
    for tf, sec in (("H1", 3600), ("H4", 14400), ("D1", 86400)):
        fr[tf] = [b for b in aggregate(m15[:i + 1], sec) if b["utc"] + sec <= close_t]
    return fr


def _clean(e):
    return (e.stage, e.direction, tuple(e.evidence), e.invalidation, None if e.decision is None else
            (e.decision.direction, round(e.decision.stop, 9), round(e.decision.target, 9), e.decision.max_bars))


class NoLookAheadTests(unittest.TestCase):
    """Every ICT stage report and every decision at bar i is identical with and without future bars."""

    @classmethod
    def setUpClass(cls):
        cls.m15 = walk()
        cls.full = rules.Ctx("XAUUSD", frames(cls.m15))

    def test_ict_evaluations_are_causal(self):
        rnd = random.Random(3)
        for i in rnd.sample(range(1500, len(self.m15) - 50), 30):
            cut = rules.Ctx("XAUUSD", truncated(self.m15, i))
            for s in ict.SETUPS:
                for long in (True, False):
                    self.assertEqual(_clean(s["fn"](self.full, i, long)), _clean(s["fn"](cut, i, long)), f"{s['key']} at {i}")

    def test_upgrade_decisions_are_causal(self):
        m15 = walk(n=12000, seed=11)
        full = rules.Ctx("NAS100", frames(m15))
        rnd = random.Random(5)
        h1 = full.a["H1"]["utc"]
        for i in rnd.sample(range(9000, len(m15) - 50), 12):
            cut = rules.Ctx("NAS100", truncated(m15, i))
            close_t = m15[i]["utc"] + M15
            for spec in upgrades.UPGRADES:
                tf = spec["timeframe"]
                jf, jc = (i, i) if tf == "M15" else (full.last_closed(tf, close_t), cut.last_closed(tf, close_t))
                a, b = spec["decide"](full, jf), spec["decide"](cut, jc)
                self.assertEqual(None if a is None else (a.direction, a.stop, a.target), None if b is None else (b.direction, b.stop, b.target), spec["key"])
        self.assertTrue(len(h1))

    def test_the_family_triggers_on_random_data_without_errors(self):
        stages = set()
        for i in range(1500, len(self.m15)):
            for s in ict.SETUPS:
                for long in (True, False):
                    stages.add(s["fn"](self.full, i, long).stage)
        self.assertTrue({"WATCHING", "DEVELOPING", "CONFIRMING"} <= stages, stages)


def flat_day(start, n, base=100.0, amp=0.5):
    bars = []
    for k in range(n):
        o = base + (amp if k % 2 else -amp) * 0.3
        c = base - (amp if k % 2 else -amp) * 0.3
        bars.append({"utc": start + k * M15, "open": o, "high": max(o, c) + 0.2, "low": min(o, c) - 0.2, "close": c, "tick_volume": 1, "spread": 0.01})
    return bars


class PrimitiveTests(unittest.TestCase):
    def test_kill_zones_use_new_york_time_with_dst(self):
        summer = rules.Ctx("EURUSD", {"M15": [{"utc": datetime(2026, 7, 1, 7, 0, tzinfo=timezone.utc).timestamp(), "open": 1, "high": 1, "low": 1, "close": 1}]})
        winter = rules.Ctx("EURUSD", {"M15": [{"utc": datetime(2026, 1, 7, 7, 0, tzinfo=timezone.utc).timestamp(), "open": 1, "high": 1, "low": 1, "close": 1}]})
        self.assertEqual(ict.ny_time(summer, 0), "03:00")
        self.assertEqual(ict.ny_time(winter, 0), "02:00")
        self.assertEqual(ict.kill_zone(3 * 60), "London kill zone")
        self.assertEqual(ict.kill_zone(10 * 60 + 15), "AM Silver Bullet")
        self.assertIsNone(ict.kill_zone(16 * 60))

    def test_fvg_needs_displacement_and_a_minimum_size(self):
        bars = flat_day(START, 40)
        bars += [{"utc": START + 40 * M15, "open": 100, "high": 100.3, "low": 99.8, "close": 100.1, "tick_volume": 1, "spread": .01},
                 {"utc": START + 41 * M15, "open": 100.1, "high": 102.2, "low": 100.0, "close": 102.0, "tick_volume": 1, "spread": .01},
                 {"utc": START + 42 * M15, "open": 102.0, "high": 102.5, "low": 101.0, "close": 102.3, "tick_volume": 1, "spread": .01}]
        ctx = rules.Ctx("XAUUSD", {"M15": bars})
        g = ict.fvg_at(ctx, 42, True)
        self.assertIsNotNone(g)
        self.assertAlmostEqual(g["bottom"], 100.3)
        self.assertAlmostEqual(g["top"], 101.0)
        self.assertIsNone(ict.fvg_at(ctx, 42, False))
        self.assertEqual(ict.fvg_state(ctx, g, 42, True)["status"], "OPEN")

    def test_a_pool_is_swept_only_by_a_close_back_inside(self):
        prev = flat_day(START - 86400 + 22 * 3600 - 86400, 96)          # a full previous NY trading day
        today = flat_day(prev[-1]["utc"] + M15, 30)
        pdl = min(b["low"] for b in prev)
        i = len(prev) + len(today)
        sweep = {"utc": today[-1]["utc"] + M15, "open": 100, "high": 100.2, "low": pdl - 0.4, "close": pdl + 0.3, "tick_volume": 1, "spread": .01}
        through = {"utc": today[-1]["utc"] + M15, "open": 100, "high": 100.2, "low": pdl - 0.4, "close": pdl - 0.2, "tick_volume": 1, "spread": .01}
        pre = flat_day(prev[0]["utc"] - 96 * M15, 96)                    # so the previous day is not block 0
        ok = rules.Ctx("XAUUSD", {"M15": pre + prev + today + [sweep]})
        bad = rules.Ctx("XAUUSD", {"M15": pre + prev + today + [through]})
        kinds = {e["kind"] for e in ict.sweeps_at(ok, len(pre) + i)}
        self.assertIn("PDL", kinds)
        self.assertNotIn("PDL", {e["kind"] for e in ict.sweeps_at(bad, len(pre) + i)})

    def test_sweep_reversal_confirms_only_after_displacement(self):
        pre = flat_day(START - 3 * 86400, 96)
        prev = flat_day(pre[-1]["utc"] + M15, 96)
        today = flat_day(prev[-1]["utc"] + M15, 30)
        pdl = min(b["low"] for b in prev)
        t = today[-1]["utc"] + M15
        sweep = {"utc": t, "open": 100, "high": 100.2, "low": pdl - 0.4, "close": pdl + 0.3, "tick_volume": 1, "spread": .01}
        weak = {"utc": t + M15, "open": pdl + 0.3, "high": 100.3, "low": pdl + 0.2, "close": 100.25, "tick_volume": 1, "spread": .01}
        strong = {"utc": t + M15, "open": pdl + 0.3, "high": 101.0, "low": pdl + 0.25, "close": 100.9, "tick_volume": 1, "spread": .01}
        base = pre + prev + today + [sweep]
        e1 = ict._sweep_reversal(rules.Ctx("XAUUSD", {"M15": base + [weak]}), len(base), True)
        e2 = ict._sweep_reversal(rules.Ctx("XAUUSD", {"M15": base + [strong]}), len(base), True)
        self.assertNotEqual(e1.stage, "CONFIRMED")
        self.assertIsNone(e1.decision)
        self.assertEqual(e2.stage, "CONFIRMED", e2)
        self.assertEqual(e2.decision.direction, "LONG")
        self.assertLess(e2.decision.stop, pdl - 0.4)
        self.assertGreater(e2.decision.target, 100.9)

    def test_family_registers_as_shadow_research(self):
        ict.register(); upgrades.register()
        for key in [s["key"] for s in ict.SETUPS] + [s["key"] for s in upgrades.UPGRADES]:
            spec = rules.BY_KEY[key]
            self.assertEqual(spec["status"], rules.RESEARCH)
            self.assertFalse(rules.alerting(spec), key)
        self.assertEqual(len({s["key"] for s in ict.SETUPS}), 8)


class ConfluenceTests(unittest.TestCase):
    def item(self, key, stage="DEVELOPING", direction="LONG", confirmed=False):
        return {"key": key, "name": key, "source": "t", "stage": stage, "direction": direction,
                "family": confluence.family_of(key), "confirmed_entry": confirmed, "tier": "EXPERIMENTAL"}

    def test_correlated_strategies_count_once(self):
        r = confluence.assess("X", [self.item("ict_sweep_reversal"), self.item("ict_mss"), self.item("ict_sweep_fvg")])
        self.assertEqual(r["independent_families"], 1)
        self.assertEqual(r["classification"], "NONE")

    def test_independent_families_agree_without_confirmation(self):
        r = confluence.assess("X", [self.item("ict_mss"), self.item("trend_momentum"), self.item("support_resistance", "WATCHING")])
        self.assertEqual(r["independent_families"], 2)
        self.assertEqual(r["classification"], "DIRECTIONAL AGREEMENT")
        self.assertFalse(r["entry_confirmed"])
        self.assertIsNotNone(r["caveat"])

    def test_confirmed_confluence_needs_a_confirmed_member(self):
        r = confluence.assess("X", [self.item("ict_mss", "CONFIRMED", confirmed=True), self.item("trend_momentum")])
        self.assertEqual(r["classification"], "CONFIRMED CONFLUENCE")
        self.assertTrue(r["entry_confirmed"])

    def test_opposition_and_internal_conflict(self):
        r = confluence.assess("X", [self.item("ict_mss"), self.item("trend_momentum"), self.item("trendline_v5", direction="SHORT")])
        self.assertEqual(r["classification"], "MIXED")
        r = confluence.assess("X", [self.item("ict_mss"), self.item("smc", direction="SHORT"), self.item("trend_momentum")])
        self.assertIn("Liquidity & structure", r["conflicted_families"])
        self.assertEqual(r["independent_families"], 1)


def perf(e_dev=0.2, e_test=0.2, ci=(0.05, 0.3), x2=0.1, folds=(0.1, 0.2, 0.1, -0.05, 0.1, 0.2, 0.1), n=400, n_test=80, e_all=0.15):
    return {"development": {"expectancy_r": e_dev}, "test": {"expectancy_r": e_test, "trades": n_test},
            "all_periods": {"trades": n, "expectancy_r": e_all, "expectancy_ci95": list(ci)}, "all_periods_x2_costs": {"expectancy_r": x2},
            "walk_forward": [{"trades": 20, "expectancy_r": f} for f in folds]}


class EvidenceTierTests(unittest.TestCase):
    def test_validated_requires_every_test(self):
        self.assertEqual(evidence_tiers.classify(perf(), holm_p=0.01)["tier"], "VALIDATED")
        self.assertEqual(evidence_tiers.classify(perf(), holm_p=0.2)["tier"], "RESEARCH")
        self.assertEqual(evidence_tiers.classify(perf(e_test=-0.1), holm_p=0.01)["tier"], "RESEARCH")
        self.assertEqual(evidence_tiers.classify(perf(x2=-0.01), holm_p=0.01)["tier"], "RESEARCH")

    def test_production_needs_forward_evidence_and_approval(self):
        fwd = {"resolved": 80, "expectancy_r": 0.1, "profit_factor": 1.3}
        self.assertEqual(evidence_tiers.classify(perf(), 0.01, fwd, deployment_approved=False)["tier"], "VALIDATED")
        self.assertEqual(evidence_tiers.classify(perf(), 0.01, {"resolved": 10, "expectancy_r": 1, "profit_factor": 9}, True)["tier"], "VALIDATED")
        self.assertEqual(evidence_tiers.classify(perf(), 0.01, fwd, deployment_approved=True)["tier"], "PRODUCTION")

    def test_negative_and_thin_records(self):
        self.assertEqual(evidence_tiers.classify(perf(ci=(-0.3, -0.05), e_all=-0.15))["tier"], "SUSPENDED")
        self.assertEqual(evidence_tiers.classify(perf(n=40))["tier"], "EXPERIMENTAL")
        self.assertEqual(evidence_tiers.classify(perf(ci=(-0.2, 0.1), e_all=-0.02))["tier"], "EXPERIMENTAL")
        self.assertEqual(evidence_tiers.classify(None)["verdict"], "Not evaluated")


if __name__ == "__main__":
    unittest.main()
