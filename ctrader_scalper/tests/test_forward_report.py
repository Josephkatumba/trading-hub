"""Forward report on a synthetic journal + synthetic M1 path (no real data, no broker)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forward import report  # noqa: E402


def synthetic_m1():
    t = pd.date_range("2026-11-19 00:00", "2026-11-21 00:00", freq="min")
    rng = np.random.default_rng(3)
    c = 3600 + np.cumsum(rng.normal(0, 0.4, len(t)))
    o = np.r_[c[0], c[:-1]]
    return pd.DataFrame({"time": t, "open": o, "high": np.maximum(o, c) + 0.2, "low": np.minimum(o, c) - 0.2,
                         "close": c, "spread_px": 0.1})


def events(m1):
    k = int(np.flatnonzero(m1["time"] == pd.Timestamp("2026-11-20 10:00"))[0])
    entry = float(m1["open"].iat[k]) + 0.1
    stop, target = entry - 4.0, entry + 6.0
    base = {"v": "tds-1.0", "run_id": "r1", "running_mode": "RealTime", "experiment_id": "fwd-xau-001", "label": "TDS-FWD1"}
    rows = [
        {**base, "event": "start", "ts": "2026-11-20T06:00:00.000Z", "execution_mode": "DemoTrading", "execution_gate": "allowed",
         "demo_verified": True, "is_live": False, "account": "****567", "broker": "IC Markets", "balance": 10000},
        {**base, "event": "signal", "ts": "2026-11-20T09:55:00.000Z", "decision": "skipped", "reason": "score 72 < 80",
         "side": "buy", "setup": "PB", "bar_close_utc": "2026-11-20T09:55:00.000Z"},
        {**base, "event": "signal", "ts": "2026-11-20T10:00:00.000Z", "decision": "opened", "side": "buy", "setup": "BRT",
         "bar_close_utc": "2026-11-20T10:00:00.000Z", "position_id": 7, "entry": entry, "entry_time": "2026-11-20T10:00:01.000Z",
         "stop": stop, "target": target, "spread": 0.11, "spread_at_fill": 0.12, "slippage": 0.02, "latency_ms": 85.0},
        {**base, "event": "close", "ts": "2026-11-20T11:30:00.000Z", "position_id": 7, "reason": "StopLoss", "units": 6,
         "entry": entry, "exit": stop - 0.05, "net": -26.5, "commission": -1.3, "swap": 0, "r_multiple": -1.06,
         "balance_after": 9973.5, "planned_stop": stop, "stop_slippage": 0.05},
        {**base, "event": "heartbeat", "ts": "2026-11-20T11:31:00.000Z", "halted": False, "halt_reason": None},
        {**base, "event": "signal", "ts": "2026-11-20T12:00:00.000Z", "running_mode": "SilentBacktesting", "decision": "opened"},
    ]
    df = pd.DataFrame(rows)
    df = df[df["running_mode"] == "RealTime"].copy()
    df["t"] = pd.to_datetime(df["ts"].str.replace("Z", ""))
    return df.reset_index(drop=True)


class ForwardReportTests(unittest.TestCase):
    def test_report_from_synthetic_day(self):
        m1 = synthetic_m1()
        rep = report.build(pd.Timestamp("2026-11-20").date(), events(m1), m1)
        self.assertEqual(rep["signals"]["total"], 2)
        self.assertEqual(rep["today"]["trades"], 1)
        self.assertFalse(rep["status"]["live_ever_seen"])
        self.assertAlmostEqual(rep["costs_today"]["actual_stop_slippage_mean"], 0.05)
        self.assertTrue(rep["reconciliation"]["available"])
        self.assertEqual(rep["reconciliation"]["fill_model"]["trades_compared"], 1)
        md = report.markdown(rep)
        self.assertIn("no validated edge", md)
        self.assertIn("At least 100", md)

    def test_no_journal_yet(self):
        rep = report.build(pd.Timestamp("2026-11-24").date(), pd.DataFrame(), None)
        self.assertFalse(rep["status"]["ever_started"])
        self.assertIn("not been started", report.markdown(rep))


if __name__ == "__main__":
    unittest.main()
