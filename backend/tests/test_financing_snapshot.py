"""Read-only financing snapshot extension: fake symbol_info objects, temporary files only."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import financing_snapshot as fs

AT = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def info(**kw):
    base = dict(currency_base="USD", currency_profit="USD", currency_margin="USD", trade_contract_size=1.0, point=0.01,
                trade_tick_size=0.01, trade_tick_value=0.01, swap_mode=2, swap_long=-1.843, swap_short=-0.023, swap_rollover3days=5)
    base.update(kw)
    return SimpleNamespace(**base)


class FinancingSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "swap_snapshots.jsonl"
        os.environ[fs.ENABLED_ENV] = "1"
        fs._seen.clear()

    def tearDown(self):
        os.environ.pop(fs.ENABLED_ENV, None)
        fs._seen.clear()
        self.tmp.cleanup()

    def rows(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def test_disabled_by_default_writes_nothing(self):
        os.environ.pop(fs.ENABLED_ENV)
        self.assertFalse(fs.offer("US500", "US500", info(), "USD", self.path, AT))
        self.assertFalse(self.path.exists())

    def test_mode2_same_currency_converted(self):
        fs.offer("US500", "US500", info(), "USD", self.path, AT)
        (row,) = self.rows()
        self.assertEqual(row["swap_mode_name"], "CURRENCY_SYMBOL")
        self.assertAlmostEqual(row["price_units_per_lot_night_long"], -1.843)
        self.assertEqual(row["account_currency"], "USD")

    def test_mode3_different_currency_left_unknown(self):
        fs.offer("GER40", "DE40", info(swap_mode=3, currency_margin="EUR", currency_profit="USD", swap_long=-5.02), "USD", self.path, AT)
        (row,) = self.rows()
        self.assertIsNone(row["price_units_per_lot_night_long"])
        self.assertIn("not assumed", row["conversion_long"])

    def test_missing_fields_recorded_as_null_not_guessed(self):
        partial = SimpleNamespace(swap_mode=3, swap_long=-7.1, swap_short=-0.09)
        fs.offer("NAS100", "USTEC", partial, None, self.path, AT)
        (row,) = self.rows()
        self.assertIsNone(row["currency_margin"])
        self.assertIsNone(row["price_units_per_lot_night_long"])

    def test_points_mode_and_append_only_once_per_day(self):
        gold = info(swap_mode=1, swap_long=-55.484, swap_short=38.822)
        self.assertTrue(fs.offer("XAUUSD", "XAUUSD", gold, "USD", self.path, AT))
        self.assertFalse(fs.offer("XAUUSD", "XAUUSD", gold, "USD", self.path, AT))
        fs._seen.clear()  # simulate engine restart: file is re-read, still no duplicate
        self.assertFalse(fs.offer("XAUUSD", "XAUUSD", gold, "USD", self.path, AT))
        self.assertTrue(fs.offer("XAUUSD", "XAUUSD", gold, "USD", self.path, AT.replace(day=21)))
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0]["price_units_per_lot_night_long"], -0.55484)

    def test_no_credentials_or_account_details_recorded(self):
        leaky = info(login=123456, password="x", balance=1000.0)
        fs.offer("US500", "US500", leaky, "USD", self.path, AT)
        text = self.path.read_text()
        for word in ("login", "password", "balance", "123456"):
            self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
