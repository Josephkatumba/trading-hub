import unittest

from backend.scanner import _trade_levels


class TradeLevelStructureTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"high": 101.0, "low": 99.5}]

    def test_long_keeps_structural_target_inside_one_risk_unit(self):
        levels = _trade_levels(
            self.rows, "LONG", 100.0, 1.0,
            [(0, 100.8)], [(0, 99.5)], 0.0, "NONE",
        )

        self.assertEqual(levels["take_profit"], 100.8)
        self.assertLess(levels["rr"], 1.0)

    def test_short_keeps_structural_target_inside_one_risk_unit(self):
        levels = _trade_levels(
            self.rows, "SHORT", 100.0, 1.0,
            [(0, 100.5)], [(0, 99.2)], 0.0, "NONE",
        )

        self.assertEqual(levels["take_profit"], 99.2)
        self.assertLess(levels["rr"], 1.0)

    def test_two_r_fallback_remains_when_no_structural_target_exists(self):
        levels = _trade_levels(
            self.rows, "LONG", 100.0, 1.0,
            [], [(0, 99.5)], 0.0, "NONE",
        )

        self.assertEqual(levels["rr"], 2.0)


if __name__ == "__main__":
    unittest.main()
