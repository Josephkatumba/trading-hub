import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import ctrader_feed as cf
import scalper_journal as sj

NOW = datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def status_doc(written, state="running", tick=None):
    return {"v": "tdc-1.0", "state": state, "written_at": iso(written), "run_id": "r1", "running_mode": "RealTime",
            "status_interval_seconds": 5, "is_live": False, "account": "*****056", "broker": "Raw Trading Ltd",
            "currency": "USD", "leverage": 100, "balance": 1000.0, "equity": 1010.0, "margin": 5.0, "free_margin": 1005.0,
            "unrealized_net": 10.0, "missing_symbols": "GBPJPY", "write_errors": 0,
            "quotes": [{"symbol": "XAUUSD", "broker_symbol": "XAUUSD", "bid": 2650.1, "ask": 2650.3, "spread": 0.2,
                        "digits": 2, "last_tick_utc": iso(tick or written), "last_bar_utc": iso(written - timedelta(minutes=1))}],
            "positions": []}


class CtraderFeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        os.environ["CTRADER_COLLECTOR_DIR"] = self.tmp.name

    def tearDown(self):
        os.environ.pop("CTRADER_COLLECTOR_DIR", None)
        self.tmp.cleanup()

    def write_status(self, doc):
        (self.dir / "status.json").write_text(json.dumps(doc))

    def test_never_started_is_disconnected(self):
        s = cf.status(self.dir, NOW)
        self.assertEqual(s["state"], "never_started")
        self.assertFalse(s["connected"])
        self.assertIsNone(s["account"])

    def test_missing_folder_is_not_installed(self):
        original = cf.collector_dir
        cf.collector_dir = lambda: None
        try:
            s = cf.status(None, NOW)
        finally:
            cf.collector_dir = original
        self.assertFalse(s["connected"])
        self.assertEqual(s["state"], "not_installed")

    def test_fresh_status_is_connected(self):
        self.write_status(status_doc(NOW - timedelta(seconds=4)))
        s = cf.status(self.dir, NOW)
        self.assertTrue(s["connected"])
        self.assertEqual(s["state"], "connected")
        self.assertEqual(s["age_seconds"], 4.0)
        self.assertEqual(s["account"]["equity"], 1010.0)
        self.assertEqual(s["missing_symbols"], ["GBPJPY"])
        self.assertTrue(s["quotes"][0]["quote_fresh"])

    def test_old_status_is_stale_not_connected(self):
        self.write_status(status_doc(NOW - timedelta(minutes=5)))
        s = cf.status(self.dir, NOW)
        self.assertEqual(s["state"], "stale")
        self.assertFalse(s["connected"])
        self.assertFalse(s["quotes"][0]["quote_fresh"])
        self.assertEqual(s["account"]["balance"], 1000.0)   # last values kept, labelled by age

    def test_stopped_and_live_refused(self):
        self.write_status(status_doc(NOW, state="stopped"))
        self.assertEqual(cf.status(self.dir, NOW)["state"], "stopped")
        self.write_status(status_doc(NOW, state="refused_live"))
        s = cf.status(self.dir, NOW)
        self.assertEqual(s["state"], "refused_live")
        self.assertFalse(s["connected"])

    def test_old_tick_marks_quote_stale(self):
        self.write_status(status_doc(NOW, tick=NOW - timedelta(minutes=10)))
        q = cf.status(self.dir, NOW)["quotes"][0]
        self.assertFalse(q["quote_fresh"])
        self.assertEqual(q["tick_age_seconds"], 600.0)

    def test_corrupt_status_is_never_started(self):
        (self.dir / "status.json").write_text("{half")
        self.assertFalse(cf.status(self.dir, NOW)["connected"])

    def test_bars_dedupe_and_limit(self):
        d = self.dir / "bars" / "XAUUSD"
        d.mkdir(parents=True)
        rows = [{"t": f"2026-11-24T10:0{i}:00.000Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10} for i in range(5)]
        (d / "M1-20261124.jsonl").write_text("\n".join(json.dumps(r) for r in rows + rows[:2]) + "\npartial{")
        b = cf.bars("xauusd", 3, self.dir)
        self.assertEqual([x["t"][11:16] for x in b], ["10:02", "10:03", "10:04"])
        self.assertEqual(cf.bars("NAS100", 3, self.dir), [])

    def test_deals_dedupe(self):
        d = {"closing_deal_id": 7, "position_id": 1, "close_time": "2026-11-24T10:00:00.000Z", "net": -1.5}
        (self.dir / "deals.jsonl").write_text(json.dumps(d) + "\n" + json.dumps({**d, "source": "close_event"}) + "\n")
        self.assertEqual(len(cf.deals(self.dir)), 1)

    def test_equity_series(self):
        lines = [{"event": "account", "ts": "2026-11-24T10:00:00.000Z", "balance": 1000, "equity": 1001}]
        (self.dir / "account-20261124.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
        self.assertEqual(cf.equity(10, self.dir)[0]["equity"], 1001)

    def test_api_endpoints(self):
        self.write_status(status_doc(datetime.now(timezone.utc)))
        app = FastAPI()
        app.include_router(sj.router)
        c = TestClient(app)
        s = c.get("/api/ctrader/status").json()
        self.assertTrue(s["connected"])
        self.assertTrue(s["read_only"])
        b = c.get("/api/ctrader/bars", params={"symbol": "XAUUSD"}).json()
        self.assertEqual(b["count"], 0)
        self.assertEqual(c.get("/api/ctrader/bars", params={"symbol": "../etc"}).status_code, 422)
        self.assertEqual(c.get("/api/ctrader/deals").json()["count"], 0)
        self.assertEqual(c.get("/api/ctrader/equity").json()["count"], 0)


if __name__ == "__main__":
    unittest.main()
