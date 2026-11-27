import unittest

import numpy as np
import pandas as pd

from research.v3.engine import Req, Series, simulate


def series(prices, name="H1", dff=0.0):
    t = pd.date_range("2019-03-05 14:00", periods=len(prices), freq="h")
    df = pd.DataFrame({"utc": t, "open": prices, "close": prices, "spread_px": 0.0})
    return Series(name, df, "utc", np.full(len(prices), dff))


class V3EngineTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.p = list(1000 * np.exp(np.cumsum(rng.normal(0, 0.001, 300))))

    def test_costs_make_flat_market_negative(self):
        s = series([1000.0] * 200)
        s.vol = np.full(s.n, 0.001)
        tr = simulate(s, [Req("H1", 150, 160, 1), Req("H1", 170, 180, -1)])
        self.assertTrue((tr["net_bp"] < 0).all())

    def test_long_short_symmetry_before_financing(self):
        s = series(self.p)
        a = simulate(s, [Req("H1", 150, 170, 1)])["net_bp"].iat[0]
        b = simulate(s, [Req("H1", 150, 170, -1)])["net_bp"].iat[0]
        self.assertLess(a + b, 0)          # both sides pay costs

    def test_one_position_at_a_time(self):
        s = series(self.p)
        tr = simulate(s, [Req("H1", 150, 170, 1), Req("H1", 160, 175, 1), Req("H1", 171, 180, 1)])
        self.assertEqual(list(tr["i"]), [150, 171])

    def test_financing_charges_longs(self):
        s = series([1000.0] * 400, name="D1", dff=5.0)
        s.vol = np.full(s.n, 0.01)
        lng = simulate(s, [Req("D1", 100, 300, 1)])["net_bp"].iat[0]
        sht = simulate(s, [Req("D1", 100, 300, -1)])["net_bp"].iat[0]
        self.assertLess(lng, sht)


if __name__ == "__main__":
    unittest.main()
