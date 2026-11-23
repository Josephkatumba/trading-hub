"""Fill model and portfolio risk rules."""
from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.indicators import ema, rsi  # noqa: E402
from engine.market import INSTRUMENTS  # noqa: E402
from engine.simulator import M1Path, RiskParams, TradeParams, run_portfolio, simulate_exit  # noqa: E402

FREE = replace(INSTRUMENTS["XAUUSD"], slippage=0.0, commission_rate=0.0)


def path(rows, spread=0.0):
    t0 = pd.Timestamp("2026-11-02 10:00")
    df = pd.DataFrame(rows, columns=["open", "high", "low"])
    df["time"] = [t0 + pd.Timedelta(minutes=i) for i in range(len(df))]
    df["spread_px"] = spread
    return M1Path(df)


def trade(sym, minute, pnl_sign, risk_px=1.0, hold=5):
    t0 = np.datetime64("2026-11-02T10:00")
    entry = 100.0
    return {"symbol": sym, "side": 1, "entry": entry, "exit": entry + pnl_sign * risk_px, "stop": entry - risk_px,
            "target": entry + risk_px, "risk_px": risk_px, "entry_time": t0 + np.timedelta64(minute, "m"),
            "exit_time": t0 + np.timedelta64(minute + hold, "m"), "reason": "x", "setup": "BRT", "score": 90,
            "session": "overlap", "signal_time": t0}


class FillTests(unittest.TestCase):
    def test_stop_wins_same_bar_tie(self):
        p = path([[100, 100.5, 99.5], [100, 103, 98]])
        ex = simulate_exit(p, 0, 1, 99.0, 1.0, TradeParams(rr=2.0), FREE)
        self.assertEqual(ex["reason"], "stop")
        self.assertAlmostEqual(ex["exit"], 99.0)

    def test_gap_through_stop_fills_at_open(self):
        p = path([[100, 100.2, 99.8], [97, 97.5, 96.5]])
        ex = simulate_exit(p, 0, 1, 99.0, 1.0, TradeParams(), FREE)
        self.assertAlmostEqual(ex["exit"], 97.0)

    def test_short_uses_ask_for_stop(self):
        df_rows = [[100, 100.1, 99.9], [100, 100.6, 99.9]]
        p = path(df_rows, spread=0.5)  # ask = bid + 0.5 -> high ask 101.1 >= stop 101
        ex = simulate_exit(p, 0, -1, 101.0, 1.0, TradeParams(), FREE)
        self.assertEqual(ex["reason"], "stop")

    def test_time_exit(self):
        p = path([[100, 100.1, 99.9]] * 10)
        ex = simulate_exit(p, 0, 1, 99.0, 1.0, TradeParams(max_hold_min=5), FREE)
        self.assertEqual(ex["reason"], "time")


class PortfolioTests(unittest.TestCase):
    def test_max_two_positions(self):
        trades = [trade("XAUUSD", 0, 1, hold=30), trade("BTCUSD", 1, 1, hold=30), trade("EURUSD", 2, 1, hold=30)]
        df = run_portfolio(trades, RiskParams())
        self.assertEqual(len(df), 2)

    def test_risk_sizing_half_percent(self):
        df = run_portfolio([trade("XAUUSD", 0, -1, risk_px=2.0)], RiskParams())
        self.assertAlmostEqual(df["cash_risk"].iloc[0], 50.0, delta=2.0)  # 0.5% of 10k
        self.assertLessEqual(df["cash_risk"].iloc[0], 50.0)

    def test_three_consecutive_losses_halt_day(self):
        trades = [trade("XAUUSD", m, -1, hold=1) for m in (0, 20, 40, 60, 80)]
        df = run_portfolio(trades, RiskParams(cooldown_min=0))
        self.assertEqual(len(df), 3)

    def test_daily_loss_budget_counts_open_risk(self):
        r = RiskParams(risk_pct=1.0, max_daily_loss_pct=1.5, max_consecutive_losses=99, cooldown_min=0)
        trades = [trade("XAUUSD", 0, 1, hold=60), trade("BTCUSD", 1, 1, hold=60)]
        df = run_portfolio(trades, r)
        self.assertEqual(len(df), 1)  # 1% open + 1% new > 1.5%


class IndicatorTests(unittest.TestCase):
    def test_ema_constant(self):
        self.assertTrue(np.allclose(ema(np.full(50, 3.0), 9), 3.0))

    def test_rsi_bounds(self):
        x = np.cumsum(np.random.default_rng(1).normal(size=500)) + 100
        r = rsi(x)
        self.assertTrue(((r >= 0) & (r <= 100)).all())
        self.assertEqual(rsi(np.arange(30.0))[-1], 100.0)


if __name__ == "__main__":
    unittest.main()
