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
        main._MT5_SESSION.update(initialized=False, initializations=0, retry_at=0)
        self.intent = mock.patch.object(main, 'read_state', return_value={'state': 'RUNNING'})
        self.intent.start()
        self.addCleanup(self.intent.stop)
        self.state = mock.patch.object(main, 'set_state')
        self.state_mock = self.state.start()
        self.addCleanup(self.state.stop)
        self.fake = CountingMT5()
        self.patch = mock.patch.object(main, "mt5", self.fake)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        main._MT5_SESSION.update(initialized=False, initializations=0, retry_at=0)

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
             mock.patch.object(main, "present_outcome_keys", return_value=set()), \
             mock.patch.object(main, "resolve_due_market_outcomes", return_value=[]):
            for _ in range(3):
                main.market_snapshot()
        self.assertEqual(self.fake.initialize_calls, 1)
        self.assertEqual(self.fake.shutdown_calls, 0)

    def test_lost_terminal_pauses_without_reinitializing(self):
        self.assertEqual(main.ensure_mt5(), (True, None))
        self.fake.terminal_alive = False
        self.assertFalse(main.ensure_mt5()[0])
        self.assertEqual(self.fake.initialize_calls, 1)
        self.state_mock.assert_called_once_with('PAUSED', 'MT5 disappeared; explicit resume required', expected='RUNNING')
        self.assertEqual(self.fake.shutdown_calls, 1)

    def test_disconnected_terminal_does_not_reinitialize_or_launch(self):
        self.assertEqual(main.ensure_mt5(), (True, None))
        with mock.patch.object(self.fake, "terminal_info", return_value=SimpleNamespace(connected=False)):
            self.assertFalse(main.ensure_mt5()[0])
        self.assertEqual(main.ensure_mt5(), (True, None))
        self.assertEqual(self.fake.initialize_calls, 1)
        self.assertEqual(self.fake.shutdown_calls, 0)

    def test_offline_terminal_reports_error_and_retries_next_time(self):
        self.fake.initialize_ok = False
        connected, error = main.ensure_mt5()
        self.assertFalse(connected)
        self.assertIn("IPC", error)
        self.assertEqual(main.health()["mt5_status"], "OFFLINE")
        self.fake.initialize_ok = True
        main._MT5_SESSION['retry_at'] = 0
        self.assertEqual(main.ensure_mt5(), (True, None))

    def test_engine_shutdown_closes_the_connection_once(self):
        main.ensure_mt5()

        async def run_lifespan():
            async with main.lifespan(main.app):
                pass

        with mock.patch.object(main.threading, 'Thread'),              mock.patch.object(main.telegram_notifier, 'start_notifier'),              mock.patch.object(main.quant_live_service, 'start'),              mock.patch('market_intel.briefings.start'):
            asyncio.run(run_lifespan())
        self.assertEqual(self.fake.shutdown_calls, 1)
        self.assertFalse(main._MT5_SESSION["initialized"])

    def test_closed_terminal_stays_closed_with_persisted_pause(self):
        import tempfile
        from ops import control
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(control, 'STATE_FILE', Path(directory) / 'control.json'), \
             mock.patch.object(main, 'read_state', side_effect=control.read_state), \
             mock.patch.object(main, 'set_state', side_effect=control.set_state):
            control.set_state('RUNNING')
            self.assertTrue(main.ensure_mt5()[0])
            self.fake.terminal_alive = False
            self.assertFalse(main.ensure_mt5()[0])
            self.assertEqual(control.read_state()['state'], 'PAUSED')
            for _ in range(10):
                self.assertFalse(main.ensure_mt5()[0])
            self.assertEqual(self.fake.initialize_calls, 1)

    def test_missing_package_is_unavailable(self):
        with mock.patch.object(main, "mt5", None):
            self.assertEqual(main.ensure_mt5(), (False, "MetaTrader5 package is unavailable"))


if __name__ == "__main__":
    unittest.main()
