"""Edge-discovery lab: no look-ahead in any generator, causal levels, statistics, pre-registration lock."""
from __future__ import annotations

import json
import math
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from research.edge import candidates, diagnostics, registry, tournament
from research.edge.market import Market

START = 1_726_000_000 - 1_726_000_000 % 86400      # a UTC midnight


class FakeHistory:
    def __init__(self, bars):
        self.full = {"M15": bars}


def bars(days=150, seed=7, vol=0.0012, drift=0.0):
    rng = random.Random(seed)
    out, price = [], 1.5
    for k in range(days * 96):
        o = price
        c = o * (1 + rng.gauss(drift, vol))
        out.append({"utc": START + 900 * k, "open": o, "close": c, "high": max(o, c) * (1 + abs(rng.gauss(0, vol / 2))),
                    "low": min(o, c) * (1 - abs(rng.gauss(0, vol / 2))), "spread": 0.0001, "tick_volume": rng.randint(20, 400)})
        price = c
    return out


def configs(family):
    for cfg in family["configs"]:
        yield ({**cfg, "sign": 1} if family["key"] == "large_move" else cfg)


class NoLookAheadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars = bars()
        cls.full = Market("GER40", FakeHistory(cls.bars))

    def test_every_generator_is_identical_when_future_bars_are_removed(self):
        cut = len(self.bars) - 20 * 96 - 37
        short = Market("GER40", FakeHistory(self.bars[:cut]))
        for family in registry.FAMILIES:
            gen = candidates.GENERATORS[family["key"]]
            for cfg in configs(family):
                a = [s for s in gen(self.full, cfg) if s["i"] < cut - 1]
                b = [s for s in gen(short, cfg) if s["i"] < cut - 1]
                self.assertEqual(a, b, f"{family['key']} {cfg} uses future bars")

    def test_signals_have_stops_on_the_loss_side(self):
        for family in registry.FAMILIES:
            for cfg in configs(family):
                for s in candidates.GENERATORS[family["key"]](self.full, cfg):
                    close = self.full.close[s["i"]]
                    self.assertTrue((s["stop"] < close) if s["dir"] == 1 else (s["stop"] > close), family["key"])

    def test_previous_day_levels_come_from_completed_days_only(self):
        ph, pl, _ = self.full.prev_day
        day = self.full.trading_day
        for i in range(200, self.full.n, 977):
            prev = np.flatnonzero(day == day[i] - 1)
            if len(prev):
                self.assertAlmostEqual(ph[i], self.full.high[prev].max())
                self.assertAlmostEqual(pl[i], self.full.low[prev].min())
                self.assertTrue(prev.max() < i)

    def test_higher_timeframe_buckets_are_complete_and_closed(self):
        h1 = self.full.frame("H1")
        self.assertTrue(np.all(h1.utc % 3600 == 0))
        for k in range(0, len(h1.close), 500):
            last = int(h1.last_m15[k])
            self.assertEqual(self.full.utc[last] + 900, h1.utc[k] + 3600)
        self.assertEqual(self.full.tf_index_at("H1", int(h1.last_m15[10])), 10)
        self.assertEqual(self.full.tf_index_at("H1", int(h1.last_m15[10]) - 1), 9)


class StatisticsTests(unittest.TestCase):
    def test_variance_ratio_of_a_random_walk_is_near_one(self):
        r = np.random.default_rng(1).normal(0, 1, 20000)
        vr, z = diagnostics.variance_ratio(r, 4)
        self.assertAlmostEqual(vr, 1.0, delta=0.05)
        self.assertLess(abs(z), 3)
        trending = np.convolve(np.random.default_rng(2).normal(0, 1, 20000), np.ones(3) / 3, mode="valid")
        self.assertGreater(diagnostics.variance_ratio(trending, 4)[0], 1.3)

    def test_large_move_continuation_sign(self):
        rng = np.random.default_rng(3)
        r = rng.normal(0, 1, 6000)
        for k in range(150, 5900, 50):
            r[k] = 6.0
            r[k + 1:k + 5] = -1.0                     # every shock reverses
        self.assertEqual(diagnostics.large_move_continuation(r)["sign"], -1)

    def test_holm_is_monotone_and_conservative(self):
        adj = tournament.holm({"a": 0.01, "b": 0.02, "c": 0.5})
        self.assertAlmostEqual(adj["a"], 0.03)
        self.assertAlmostEqual(adj["b"], 0.04)
        self.assertEqual(adj["c"], 0.5)

    def test_busy_filter_keeps_one_position(self):
        row = lambda utc, j, x: ("f", 0, "2R", utc, j, x, 1.0, 0.9, 1, 0, 1.0, 16, "RANGING", "TP")
        kept = tournament.busy_filter([row(0, 0, 10), row(5, 5, 7), row(20, 11, 12)])
        self.assertEqual([r[4] for r in kept], [0, 11])

    def test_one_sided_p(self):
        self.assertAlmostEqual(tournament.p_one_sided({"t_stat": 1.645}), 0.05, places=3)
        self.assertIsNone(tournament.p_one_sided({"t_stat": None}))


class PreregistrationTests(unittest.TestCase):
    def test_refuses_a_changed_registry(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(tournament, "out_dir", return_value=Path(tmp)):
            first = tournament.preregister()
            self.assertEqual(tournament.preregister()["fingerprint"], first["fingerprint"])
            with mock.patch.object(registry, "fingerprint", return_value="different"):
                with self.assertRaises(SystemExit):
                    tournament.preregister()
            rows = [json.loads(line) for line in (Path(tmp) / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)

    def test_registry_is_small_and_counted(self):
        for family in registry.FAMILIES:
            self.assertLessEqual(len(family["configs"]), 9)
            self.assertIn(family["key"], candidates.GENERATORS)
        self.assertEqual(registry.trial_count(), sum(len(f["configs"]) for f in registry.FAMILIES) * len(registry.EXITS))


if __name__ == "__main__":
    unittest.main()
