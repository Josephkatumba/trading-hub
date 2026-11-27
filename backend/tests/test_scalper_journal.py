import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import scalper_journal as sj


def rec(evt, ts, **kw):
    return {"v": "tds-1.0", "event": evt, "ts": ts, "run_id": "r1", "running_mode": "RealTime", **kw}


class ScalperJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        os.environ["SCALPER_JOURNAL_DIR"] = self.tmp.name
        lines = [
            rec("start", "2026-11-24T08:00:00.000Z", demo_verified=True, is_live=False, account="****123", balance=10000.0,
                currency="USD", broker="IC Markets"),
            rec("signal", "2026-11-24T08:05:00.000Z", decision="skipped", reason="score 70 < 80"),
            rec("signal", "2026-11-24T08:10:00.000Z", decision="opened", symbol="XAUUSD", position_id=1),
            rec("close", "2026-11-24T08:40:00.000Z", position_id=1, symbol="XAUUSD", side="buy", setup="BRT", session="london",
                net=75.0, commission=-4.0, r_multiple=1.5, balance_after=10075.0, reason="TakeProfit"),
            rec("close", "2026-11-24T09:40:00.000Z", position_id=2, symbol="XAUUSD", side="sell", setup="PB", session="london",
                net=-50.0, commission=-4.0, r_multiple=-1.0, balance_after=10025.0, reason="StopLoss"),
            rec("close", "2026-11-24T09:40:00.000Z", position_id=2, symbol="XAUUSD", side="sell", setup="PB", session="london",
                net=-50.0, commission=-4.0, r_multiple=-1.0, balance_after=10025.0, reason="StopLoss"),  # duplicate
            rec("heartbeat", "2026-11-24T09:41:00.000Z", balance=10025.0, equity=10020.0, realized_today=25.0, open_risk=0.0,
                daily_limit=300.0, consecutive_losses=1, halted=False, positions=[]),
            {"event": "close", "ts": "2026-11-24T09:50:00.000Z", "running_mode": "SilentBacktesting", "net": 999},
        ]
        (self.dir / "journal-20261124.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")

    def tearDown(self):
        os.environ.pop("SCALPER_JOURNAL_DIR", None)
        self.tmp.cleanup()

    def test_summary_counts_real_closes_only(self):
        s = sj.summary(now=datetime(2026, 11, 24, 9, 42, tzinfo=timezone.utc))
        p = s["performance"]
        self.assertEqual(p["trades"], 2)
        self.assertEqual(p["net_pnl"], 25.0)
        self.assertEqual(p["win_rate"], 50.0)
        self.assertEqual(p["profit_factor"], 1.5)
        self.assertAlmostEqual(p["max_drawdown_pct"], 0.5, places=2)
        self.assertEqual(s["bot_status"], "running")
        self.assertTrue(s["account"]["demo_verified"])
        self.assertFalse(s["live_account_ever_seen"])
        self.assertEqual(s["signals"]["skip_reasons"], {"score": 1})

    def test_offline_when_heartbeat_stale(self):
        s = sj.summary(now=datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(s["bot_status"], "offline")

    def test_daily_report_markdown(self):
        r = sj.daily_report("2026-11-24")
        self.assertEqual(r["stats"]["trades"], 2)
        self.assertIn("far too few", r["markdown"])

    def test_empty_journal(self):
        os.environ["SCALPER_JOURNAL_DIR"] = str(self.dir / "missing")
        s = sj.summary(events=[])
        self.assertEqual(s["bot_status"], "never_started")
        self.assertEqual(s["performance"]["trades"], 0)


if __name__ == "__main__":
    unittest.main()
