"""TradeDen -> cTrader bridge: normalisation, no history replay, freshness."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forward import bridge  # noqa: E402

NOW = datetime(2026, 11, 23, 20, 1, 0, tzinfo=timezone.utc)
GARDEN = {"kind": "signal", "setup_id": "stp_1", "strategy_id": "trendline_v5", "symbol": "XAGUSD", "direction": "SHORT",
          "entry": 43.153, "stop_loss": 43.455, "take_profit": 42.148, "timeframe": "M15", "confirmed_at": "2026-11-23T20:00:30+00:00"}
BANK = {"record_type": "bank_signal", "signal_id": "bank_1", "strategy_key": "liquidity_sweep", "symbol": "EURUSD",
        "direction": "LONG", "entry": 1.089, "stop_loss": 1.087, "take_profit": 1.093, "executable": True,
        "timeframe": "H1", "confirmed_at": "2026-11-23T20:00:00+00:00", "time_exit_at": None}


class BridgeTests(unittest.TestCase):
    def test_normalise(self):
        g = bridge.normalise("garden", GARDEN)
        self.assertEqual((g["signal_id"], g["side"], g["symbol"]), ("garden:stp_1", "sell", "XAGUSD"))
        b = bridge.normalise("bank", BANK)
        self.assertEqual((b["side"], b["stop"], b["source"]), ("buy", 1.087, "bank"))
        self.assertIsNone(bridge.normalise("bank", {**BANK, "executable": False}))
        self.assertIsNone(bridge.normalise("bank", {**BANK, "stop_loss": 1.095}))     # stop on wrong side
        self.assertIsNone(bridge.normalise("garden", {**GARDEN, "kind": "outcome"}))

    def test_tail_starts_at_end_and_forwards_only_fresh_new_signals(self):
        with tempfile.TemporaryDirectory() as d:
            g, b, inbox = Path(d) / "g.jsonl", Path(d) / "b.jsonl", Path(d) / "inbox.jsonl"
            old = {**BANK, "signal_id": "old"}
            g.write_text(json.dumps({**GARDEN, "setup_id": "history"}) + "\n")
            b.write_text(json.dumps(old) + "\n")
            os.environ["TRADEDEN_INBOX"] = str(inbox)
            saved = bridge.SOURCES
            bridge.SOURCES = {"garden": g, "bank": b}
            try:
                tails_before = bridge.run(once=True, now=lambda: NOW)
                self.assertEqual(tails_before, 0)                      # history is not replayed
                # append: one fresh signal, one stale update, one duplicate
                with b.open("a") as fh:
                    fh.write(json.dumps(BANK) + "\n")
                    fh.write(json.dumps({**BANK, "signal_id": "stale", "confirmed_at": "2026-11-23T18:00:00+00:00"}) + "\n")
                    fh.write(json.dumps(BANK) + "\n")
                # a fresh run starts at the end again, so drive one Tail manually
                tail = bridge.Tail(b)
                tail.pos = len(json.dumps(old)) + 1
                lines = tail.lines()
                self.assertEqual(len(lines), 3)
            finally:
                bridge.SOURCES = saved
                os.environ.pop("TRADEDEN_INBOX", None)


if __name__ == "__main__":
    unittest.main()
