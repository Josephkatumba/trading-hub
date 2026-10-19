"""T-032 research lab: no look-ahead in the replay, simulator fills/costs/ambiguity, metrics."""
from __future__ import annotations

import copy
import random
import unittest

from research import metrics
from research.replay import M15_COUNT, SymbolHistory
from research.simulate import STOP_SLIPPAGE_SPREADS, simulate

START = 1_700_000_000 - 1_700_000_000 % 86400          # a midnight, raw = utc in these fixtures
TF = {"M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}


def synthetic(n_m15=212 * 96, seed=3, spread=0.0002):
    rng = random.Random(seed)
    m15, price = [], 1.1
    for k in range(n_m15):
        o = price
        c = o + rng.uniform(-0.002, 0.002)
        bar = {"time": START + 900 * k, "utc": START + 900 * k, "open": o, "close": c,
               "high": max(o, c) + rng.uniform(0, 0.001), "low": min(o, c) - rng.uniform(0, 0.001),
               "tick_volume": rng.randint(10, 100), "spread": spread}
        m15.append(bar)
        price = c
    frames = {"M15": m15}
    for tf, seconds in TF.items():
        if tf == "M15":
            continue
        groups = {}
        for bar in m15:
            groups.setdefault(bar["time"] - (bar["time"] - START) % seconds, []).append(bar)
        frames[tf] = [{"time": t, "utc": t, "open": g[0]["open"], "close": g[-1]["close"], "high": max(b["high"] for b in g),
                       "low": min(b["low"] for b in g), "tick_volume": sum(b["tick_volume"] for b in g), "spread": spread}
                      for t, g in sorted(groups.items())]
    frames["M1"] = []
    return frames


def history(frames, symbol="EURUSD"):
    return SymbolHistory(symbol, {"digits": 5, "point": 0.00001, "tick_size": 0.00001}, frames)


def as_plain(built):
    market, quote = built
    return (market.rows, market.higher_rows, {k: list(v) for k, v in market.bars.items()}, quote)


class NoLookAheadTests(unittest.TestCase):
    def test_inputs_at_bar_i_ignore_everything_after_its_open(self):
        frames = synthetic()
        clean = history(frames)
        # Bar indices where every timeframe has enough closed history (200 D1 bars needs ~200 days),
        # including hour, 4-hour and day boundaries.
        first = next(k for k in range(M15_COUNT, len(frames["M15"])) if clean.market_input(k))
        for i in (first, first + 1, first + 3, first + 4, first + 15, first + 16, first + 95, first + 96, first + 97):
            now = frames["M15"][i]["time"]
            dirty = copy.deepcopy(frames)
            for bar in dirty["M15"][i + 1:]:
                bar.update(open=9.9, high=9.9, low=0.1, close=9.9)
            dirty["M15"][i].update(high=9.9, low=0.1, close=7.7)     # only its open was known
            for tf in ("H1", "H4", "D1"):
                for bar in dirty[tf]:
                    if bar["time"] + TF[tf] > now:                    # still forming or in the future
                        bar.update(high=9.9, low=0.1, close=7.7)
            self.assertEqual(as_plain(clean.market_input(i)), as_plain(history(dirty).market_input(i)), f"look-ahead at bar {i}")

    def test_forming_bars_and_quote(self):
        frames = synthetic()
        h = history(frames)
        i = next(k for k in range(M15_COUNT, len(frames["M15"])) if h.market_input(k)) + 5
        market, quote = h.market_input(i)
        last = market.rows[-1]
        self.assertEqual((last["open"], last["high"], last["low"], last["close"]), (frames["M15"][i]["open"],) * 4)
        self.assertEqual(len(market.rows), M15_COUNT + 1)
        self.assertEqual(quote["bid"], frames["M15"][i]["open"])
        self.assertAlmostEqual(quote["ask"] - quote["bid"], frames["M15"][i]["spread"])
        for tf in ("H1", "H4", "D1"):
            closed, forming = market.bars[tf][:-1], market.bars[tf][-1]
            self.assertTrue(all(b["time"] + TF[tf] <= frames["M15"][i]["time"] for b in closed))
            self.assertLessEqual(forming["time"], frames["M15"][i]["time"])
            self.assertEqual(forming["close"], frames["M15"][i]["open"])


def flat(n=50, price=1.0, spread=0.0, **over):
    frames = {"M15": [{"time": START + 900 * k, "utc": START + 900 * k, "open": price, "high": price + 0.001,
                       "low": price - 0.001, "close": price, "tick_volume": 1, "spread": spread} for k in range(n)],
              "H1": [], "H4": [], "D1": [], "M1": []}
    for k, values in over.items():
        frames["M15"][int(k[1:])].update(values)
    return frames


def signal(direction="LONG", entry=1.0, sl=0.99, tp=1.02, index=0):
    return {"index": index, "direction": direction, "entry": entry, "stop_loss": sl, "take_profit": tp}


class SimulatorTests(unittest.TestCase):
    def test_long_target_and_stop_with_slippage_and_commission(self):
        h = history(flat(b5={"high": 1.025}), "NAS100")
        self.assertEqual(simulate(signal(), h)["outcome"], "TP")
        self.assertAlmostEqual(simulate(signal(), h)["r"], 2.0)
        h = history(flat(spread=0.002, b5={"low": 0.985}), "EURUSD")
        result = simulate(signal(), h)
        expected = (-(0.01 + STOP_SLIPPAGE_SPREADS * 0.002) - 0.00007) / 0.01
        self.assertEqual(result["outcome"], "SL")
        self.assertAlmostEqual(result["r"], round(expected, 4))

    def test_short_exits_at_the_ask(self):
        # Bid high 1.0095 + spread 0.001 reaches the 1.01 stop of a SELL.
        h = history(flat(spread=0.001, b3={"high": 1.0095}, b6={"low": 0.97}), "NAS100")
        self.assertEqual(simulate(signal("SHORT", 1.0, 1.01, 0.98), h)["outcome"], "SL")
        # Target needs the ask at 0.98: bid low 0.9795 + 0.001 spread is not enough.
        h = history(flat(spread=0.001, b3={"low": 0.9795}), "NAS100")
        self.assertNotEqual(simulate(signal("SHORT", 1.0, 1.01, 0.98), h)["outcome"], "TP")

    def test_gap_through_stop_fills_at_open(self):
        h = history(flat(b4={"open": 0.97, "low": 0.965, "high": 0.975, "close": 0.97}), "NAS100")
        result = simulate(signal(), h)
        self.assertEqual(result["outcome"], "SL")
        self.assertAlmostEqual(result["r"], -3.0)

    def test_same_candle_is_ambiguous_without_m1_and_pessimistic(self):
        h = history(flat(b4={"high": 1.03, "low": 0.98}), "NAS100")
        result = simulate(signal(), h)
        self.assertEqual(result["outcome"], "AMBIGUOUS")
        self.assertAlmostEqual(result["r"], -1.0)
        self.assertAlmostEqual(result["r_if_target"], 2.0)

    def test_same_candle_resolved_by_m1(self):
        frames = flat(b4={"high": 1.03, "low": 0.98})
        t = START + 900 * 4
        frames["M1"] = [{"utc": t + 60 * k, "open": 1.0, "high": 1.001, "low": 0.999, "close": 1.0, "spread": 0.0} for k in range(15)]
        frames["M1"][3]["high"] = 1.03
        frames["M1"][7]["low"] = 0.98
        self.assertEqual(simulate(signal(), history(frames, "NAS100"))["outcome"], "TP")

    def test_timeout_open_and_invalid(self):
        h = history(flat(n=600), "NAS100")
        self.assertEqual(simulate(signal(), h, max_bars=100)["outcome"], "TIMEOUT")
        self.assertEqual(simulate(signal(index=590), h, max_bars=100)["outcome"], "OPEN")
        self.assertEqual(simulate(signal(sl=1.01), h)["outcome"], "INVALID_PLAN")

    def test_cost_multiplier_makes_results_worse(self):
        h = history(flat(spread=0.001, b5={"high": 1.025}), "EURUSD")
        base, stressed = simulate(signal(), h), simulate(signal(), h, cost_multiplier=2.0)
        self.assertLess(stressed["r"], base["r"])


class MetricsTests(unittest.TestCase):
    def test_summary(self):
        trades = [{"outcome": "TP", "r": 2.0}, {"outcome": "SL", "r": -1.0}, {"outcome": "SL", "r": -1.0},
                  {"outcome": "AMBIGUOUS", "r": -1.0, "r_if_target": 2.0}, {"outcome": "TP", "r": 2.0}]
        s = metrics.summarize(trades, months=1)
        self.assertEqual((s["trades"], s["wins"], s["losses"], s["ambiguous"]), (5, 2, 2, 1))
        self.assertEqual(s["win_rate"], 0.5)
        self.assertEqual(s["expectancy_r"], 0.2)
        self.assertEqual(s["expectancy_r_optimistic"], 0.8)
        self.assertEqual(s["profit_factor"], round(4 / 3, 3))
        self.assertEqual(s["max_drawdown_r"], 3.0)          # +2, -1, -1, -1, +2
        self.assertFalse(s["sufficient"])
        low, high = s["expectancy_ci95"]
        self.assertLessEqual(low, 0.2)
        self.assertGreaterEqual(high, 0.2)

    def test_drawdown(self):
        self.assertEqual(metrics.max_drawdown([1, -1, -1, 2, -3, 1]), 3.0)


if __name__ == "__main__":
    unittest.main()


class TrailingAndCostTests(unittest.TestCase):
    def test_trailing_stop_moves_only_after_a_bar_closes(self):
        # Long from 1.00, stop 0.99, trail 0.01. Bar 2 rallies to 1.05 (stop moves to 1.04 for bar 3);
        # bar 3 opens at 1.045 and drops to 1.035: exit at the trailed stop, in profit. (A bar opening
        # below the trailed stop fills at its open instead: the gap rule.)
        frames = flat(b2={"high": 1.05, "close": 1.045}, b3={"open": 1.045, "low": 1.035, "high": 1.046})
        h = history(frames, "NAS100")
        s = {**signal(), "take_profit": None}
        result = simulate(s, h, trail=0.01)
        self.assertEqual(result["outcome"], "TRAIL")
        self.assertAlmostEqual(result["r"], 4.0)
        # The same bar's high must not tighten its own stop: a bar spanning 1.05 down to 0.995
        # does not stop out at the trailed level within that bar.
        frames = flat(b2={"high": 1.05, "low": 0.995})
        self.assertNotEqual(simulate(s, history(frames, "NAS100"), trail=0.01, max_bars=3)["outcome"], "TRAIL")

    def test_no_target_requires_a_trail(self):
        h = history(flat(), "NAS100")
        self.assertEqual(simulate({**signal(), "take_profit": None}, h)["outcome"], "INVALID_PLAN")

    def test_buy_entry_spread_scales_with_cost_multiplier(self):
        h = history(flat(spread=0.002, b5={"high": 1.025}), "NAS100")
        base = simulate(signal(), h)["r"]
        self.assertAlmostEqual(simulate(signal(), h, cost_multiplier=2.0)["r"], base - 0.002 / 0.01, places=6)
        self.assertAlmostEqual(simulate(signal(), h, cost_multiplier=0.0)["r"], base + 0.002 / 0.01, places=6)


class GeneratorLookAheadTests(unittest.TestCase):
    def test_v6_generators_ignore_data_after_the_decision(self):
        from research import v6
        frames = synthetic(n_m15=240 * 96, seed=11)
        cut = len(frames["M15"]) - 30 * 96
        cut_utc = frames["M15"][cut]["utc"]

        def build(fr):
            h = history(fr)
            v6._H1.pop(h.symbol, None)
            for tf in ("H1", "H4", "D1"):
                v6._TF.pop((h.symbol, tf), None)
            import research.experiments as ex
            ex._FEATURES.pop(h.symbol, None)
            out = (v6.donchian_trend(h, 20, 2.0, "trail2", True) + v6.trend_pullback(h, 1.5, "fixed2")
                   + v6.opening_range_breakout(h, 1.5, "far", 3.0) + v6.bollinger_reversion(h, 2.0, "1.5R")
                   + v6.weekly_tsmom(h, 20, 1.5, "week") + v6.h4_donchian(h, 20, 2.0, "fixed2")
                   + v6.squeeze_breakout(h, 0.2, "fixed2"))
            return sorted((s["strategy_id"], s["index"], s["direction"], round(s["entry"], 10), round(s["stop_loss"], 10))
                          for s in out if s["utc"] < cut_utc)

        clean = build(copy.deepcopy(frames))
        self.assertTrue(clean, "generators produced no signals on the fixture")
        self.assertGreaterEqual(len({row[0] for row in clean}), 5, "most generators should fire on the fixture")
        dirty = copy.deepcopy(frames)
        for tf in ("M15", "H1", "H4", "D1"):
            for bar in dirty[tf]:
                if bar["utc"] >= cut_utc - (3600 if tf == "H1" else 0) and tf != "M15" or tf == "M15" and bar["utc"] >= cut_utc:
                    bar.update(open=5.0, high=9.0, low=0.5, close=5.0)
        self.assertEqual(clean, build(dirty))


class RoundThreeLookAheadTests(unittest.TestCase):
    def test_regime_and_inside_bar_ignore_future_data(self):
        from research import v6, v6_round3 as r3
        frames = synthetic(n_m15=240 * 96, seed=5)
        cut = len(frames["M15"]) - 20 * 96
        cut_utc = frames["M15"][cut]["utc"]

        def build(fr):
            h = history(fr)
            v6._H1.pop(h.symbol, None)
            r3._REGIME.pop(h.symbol, None)
            for tf in ("H1", "H4", "D1"):
                v6._TF.pop((h.symbol, tf), None)
            regimes = [r3.regime(h, i) for i in range(cut - 200, cut, 7)]
            bars = sorted((s["index"], s["direction"], round(s["stop_loss"], 10))
                          for s in r3.inside_bar_breakout(h, 2.0, False) if s["utc"] < cut_utc)
            return regimes, bars

        clean = build(copy.deepcopy(frames))
        self.assertTrue(any(r != "UNKNOWN" for r in clean[0]))
        self.assertTrue(clean[1], "inside-bar generator produced no signals on the fixture")
        dirty = copy.deepcopy(frames)
        for tf in ("M15", "H1", "H4", "D1"):
            seconds = TF[tf]
            for bar in dirty[tf]:
                if bar["utc"] + seconds > cut_utc:          # every bar not closed by the cut
                    bar.update(open=5.0, high=9.0, low=0.5, close=5.0)
        self.assertEqual(clean, build(dirty))

    def test_holm_and_p_values(self):
        from research import v6_round3 as r3
        adjusted = r3.holm({"a": 0.01, "b": 0.04, "c": 0.03})
        self.assertEqual(adjusted, {"a": 0.03, "c": 0.06, "b": 0.06})
        self.assertLess(r3.one_sided_p([0.5] * 20 + [-0.2] * 20), 0.05)
        self.assertIsNone(r3.one_sided_p([1.0] * 10))


class FinancingTests(unittest.TestCase):
    def test_rollover_count_and_triple_day(self):
        from datetime import datetime, timezone
        from research.simulate import rollovers
        ts = lambda *a: datetime(*a, tzinfo=timezone.utc).timestamp()
        # 17:00 New York = 21:00 UTC in October (EDT). Tue 20:00 -> Wed 22:00 UTC crosses Tue's rollover only.
        self.assertEqual(rollovers(ts(2026, 10, 13, 20), ts(2026, 10, 14, 20), 3), 1)
        # Wed 20:00 -> Thu 20:00 UTC crosses Wednesday's rollover: triple with FX's day 3 (Wednesday).
        self.assertEqual(rollovers(ts(2026, 10, 14, 20), ts(2026, 10, 15, 20), 3), 3)
        self.assertEqual(rollovers(ts(2026, 10, 14, 20), ts(2026, 10, 15, 20), None), 1)
        self.assertEqual(rollovers(ts(2026, 10, 14, 10), ts(2026, 10, 14, 20), 3), 0)

    def test_financing_modes(self):
        from research.simulate import financing_per_night
        self.assertAlmostEqual(financing_per_night({"swap_mode": 1, "swap_long": -8.0, "point": 0.00001}, True, 1.1), 0.00008)
        self.assertAlmostEqual(financing_per_night({"swap_mode": 2, "swap_long": -1.8, "contract_size": 1.0}, True, 7700), 1.8)
        self.assertAlmostEqual(financing_per_night({"swap_mode": 5, "swap_long": -20.0}, True, 36000), 20.0)
        self.assertAlmostEqual(financing_per_night({"swap_mode": 1, "swap_short": 1.4, "point": 0.00001}, False, 1.1), -0.000014)
        self.assertEqual(financing_per_night({}, True, 1.0), 0.0)

    def test_overnight_hold_is_charged(self):
        frames = flat(n=200)
        h = history(frames, "NAS100")
        h.meta = {"swap_mode": 3, "swap_long": -2.0, "contract_size": 1.0, "swap_rollover3days": 5}
        free = simulate(signal(), history(flat(n=200), "NAS100"), max_bars=150)
        charged = simulate(signal(), h, max_bars=150)
        self.assertEqual(free["outcome"], "TIMEOUT")
        self.assertLess(charged["r"], free["r"])
        self.assertGreater(charged["financing_r"], 0)
