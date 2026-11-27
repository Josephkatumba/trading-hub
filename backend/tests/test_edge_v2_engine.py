import unittest

import numpy as np
import pandas as pd

from research.edge_v2.engine import Book, Signal, simulate, summarize, t_p


def frame(rows, spread=0.0, atr=1.0):
    t0 = pd.Timestamp("2025-03-04 14:00")   # Tuesday 09:00 New York: not a blocked bar
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["utc"] = [t0 + pd.Timedelta(minutes=15 * k) for k in range(len(df))]
    df["spread_px"] = spread
    df["atr"] = atr
    df["next_gap_min"] = 15.0
    df["session"] = "overlap"
    df["ny_min"] = (9 * 60 + 15 * np.arange(len(df))) % 1440
    df["ny_wd"] = 1
    return df


class EngineTests(unittest.TestCase):
    def test_stop_first_when_both_hit(self):
        b = Book(frame([[100, 100, 100, 100], [100, 103, 98, 100], [100, 100, 100, 100]]))
        tr = simulate(b, [Signal(0, 1, 99.0, target_r=1.0)])
        self.assertEqual(tr["reason"].iat[0], "stop")
        self.assertLess(tr["r"].iat[0], -1.0)          # slippage + commission make it worse than -1R

    def test_target_is_limit(self):
        b = Book(frame([[100, 100, 100, 100], [100, 101.5, 99.5, 101], [101, 101, 101, 101]]))
        tr = simulate(b, [Signal(0, 1, 98.5, target_r=0.5)])
        self.assertEqual(tr["reason"].iat[0], "target")

    def test_short_stop_on_ask(self):
        b = Book(frame([[100, 100, 100, 100], [100, 100.6, 99.9, 100], [100, 100, 100, 100]], spread=0.5))
        tr = simulate(b, [Signal(0, -1, 101.0, target_r=3.0)])
        self.assertEqual(tr["reason"].iat[0], "stop")

    def test_rejects_tiny_stop(self):
        b = Book(frame([[100, 100, 100, 100], [100, 100, 100, 100]], atr=2.0))
        self.assertTrue(simulate(b, [Signal(0, 1, 99.5, target_r=2.0)]).empty)

    def test_one_position_at_a_time(self):
        rows = [[100, 100.2, 99.8, 100]] * 10
        b = Book(frame(rows))
        tr = simulate(b, [Signal(0, 1, 99.0, exit_idx=6), Signal(2, 1, 99.0, exit_idx=8), Signal(7, 1, 99.0, exit_idx=9)])
        self.assertEqual(list(tr["i"]), [0, 7])

    def test_stats(self):
        r = np.r_[np.full(60, 1.0), np.full(40, -1.0)]
        t, p = t_p(r)
        self.assertGreater(t, 1.9)
        self.assertLess(p, 0.05)
        s = summarize(pd.DataFrame({"r": r, "entry_utc": pd.date_range("2025-01-01", periods=100, freq="D")}))
        self.assertEqual(s["profit_factor"], 1.5)


if __name__ == "__main__":
    unittest.main()
