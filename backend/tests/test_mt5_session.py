"""The MT5 connection is reused across requests and recovers when the terminal goes away."""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import main  # noqa: E402


class CountingMT5:
    def __init__(self, initialize_ok=True):
        self.initialize_ok = initialize_ok
        self.terminal_alive = True
        self.initialize_calls = 0
        self.shutdown_calls = 0

    def initialize(self):
        self.initialize_calls += 1
        self.terminal_alive = self.initialize_ok
        return self.initialize_ok

    def shutdown(self):
        self.shutdown_calls += 1

    def terminal_info(self):
        return SimpleNamespace(connected=True) if self.terminal_alive else None

    def account_info(self):
        return SimpleNamespace(login=1, server="x")

    def version(self):
        return (500, 1, "d")

    def symbols_total(self):
        return 1

    def last_error(self):
        return (-10003, "IPC initialize failed")


class MT5SessionTests(unittest.TestCase):
    def setUp(self):
        main._MT5_SESSION.update(initialized=False, initializations=0)
        self.fake = CountingMT5()
        self.patch = mock.patch.object(main, "mt5", self.fake)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        main._MT5_SESSION.update(initialized=False, initializations=0)

    def test_repeated_health_checks_initialize_once_and_never_shut_down(self):
        for _ in range(5):
            self.assertEqual(main.health()["mt5_status"], "CONNECTED")
        self.assertEqual(self.fake.initialize_calls, 1)
        self.assertEqual(self.fake.shutdown_calls, 0)

    def test_repeated_scans_reuse_the_connection(self):
        with mock.patch.object(main, "mt5_symbol", return_value=None), \
             mock.patch.object(main, "record_markets"), \
             mock.patch.object(main, "confirmation_events", return_value=[]), \
             mock.patch.object(main, "snapshots_by_observation_id", return_value={}), \
             mock.patch.object(main, "outcome_watch_snapshots", return_value=[]), \
             mock.patch.object(main, "list_records", return_value=[]), \
             mock.patch.object(main, "resolve_due_market_outcomes", return_value=[]):
            for _ in range(3):
                main.market_snapshot()
        self.assertEqual(self.fake.initialize_calls, 1)
        self.assertEqual(self.fake.shutdown_calls, 0)

    def test_lost_terminal_is_reinitialized(self):
        self.assertEqual(main.ensure_mt5(), (True, None))
        self.fake.terminal_alive = False
        self.assertEqual(main.ensure_mt5(), (True, None))
        self.assertEqual(self.fake.initialize_calls, 2)
        self.assertEqual(self.fake.shutdown_calls, 1)

    def test_offline_terminal_reports_error_and_retries_next_time(self):
        self.fake.initialize_ok = False
        connected, error = main.ensure_mt5()
        self.assertFalse(connected)
        self.assertIn("IPC", error)
        self.assertEqual(main.health()["mt5_status"], "OFFLINE")
        self.fake.initialize_ok = True
        self.assertEqual(main.ensure_mt5(), (True, None))

    def test_engine_shutdown_closes_the_connection_once(self):
        main.ensure_mt5()

        async def run_lifespan():
            async with main.lifespan(main.app):
                pass

        asyncio.run(run_lifespan())
        self.assertEqual(self.fake.shutdown_calls, 1)
        self.assertFalse(main._MT5_SESSION["initialized"])

    def test_missing_package_is_unavailable(self):
        with mock.patch.object(main, "mt5", None):
            self.assertEqual(main.ensure_mt5(), (False, "MetaTrader5 package is unavailable"))


if __name__ == "__main__":
    unittest.main()
