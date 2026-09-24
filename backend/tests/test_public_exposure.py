"""Public engine responses must not leak MT5 account identifiers."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import main  # noqa: E402

SECRET_LOGIN = 333840872
SECRET_SERVER = "ExampleBroker-Demo 7"


class FakeMT5:
    def initialize(self):
        return True

    def shutdown(self):
        return None

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def account_info(self):
        return SimpleNamespace(login=SECRET_LOGIN, server=SECRET_SERVER, balance=10123.45, equity=10111.0)

    def version(self):
        return (500, 4000, "01 Jan 2026")

    def symbols_total(self):
        return 42

    def last_error(self):
        return (0, "ok")


class PublicExposureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.heartbeat = Path(self.tmp.name) / "trading_hub_heartbeat.json"
        self.heartbeat.write_text(json.dumps({
            "bridge": "Trading Hub MT5 Bridge", "version": "1.0", "timestamp": "2026.09.24 10:00:00",
            "login": SECRET_LOGIN, "server": SECRET_SERVER, "terminal_build": 4000,
            "symbol": "XAUUSD", "bid": 1, "ask": 2, "balance": 10123.45, "equity": 10111.0,
            "execution_enabled": False}), encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"TRADING_HUB_BRIDGE_FILE": str(self.heartbeat)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_health_keeps_status_but_not_login_server_or_balances(self):
        with mock.patch.object(main, "mt5", FakeMT5()):
            payload = main.health()
        text = json.dumps(payload)
        self.assertNotIn(str(SECRET_LOGIN), text)
        self.assertNotIn(SECRET_SERVER, text)
        self.assertNotIn("10123.45", text)
        self.assertNotIn(self.tmp.name.replace("\\", "\\\\"), text)
        self.assertNotIn("login", payload["account"])
        self.assertEqual(payload["account"], {"available": True})
        self.assertEqual(payload["mt5_status"], "CONNECTED")
        self.assertEqual(payload["bridge"]["status"], "CONNECTED")
        self.assertIn(payload["data_freshness"]["status"], {"FRESH", "STALE", "UNKNOWN"})

    def test_old_bridge_heartbeat_is_reported_stale(self):
        old = time.time() - main.BRIDGE_STALE_SECONDS - 30
        os.utime(self.heartbeat, (old, old))
        bridge = main.mt5_bridge_heartbeat()
        self.assertEqual(bridge["status"], "STALE")
        self.assertFalse(bridge["connected"])

    def test_missing_bridge_is_offline_without_path(self):
        self.heartbeat.unlink()
        self.assertEqual(main.mt5_bridge_heartbeat(), {"connected": False, "status": "OFFLINE"})


class CorsConfigTests(unittest.TestCase):
    def test_default_origins_are_local_dev_only(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TRADING_HUB_CORS_ORIGINS", None)
            origins = main.configured_cors_origins()
        self.assertNotIn("*", origins)
        self.assertTrue(all("localhost" in o or "127.0.0.1" in o for o in origins))

    def test_wildcard_and_paths_are_rejected(self):
        for bad in ("*", "https://example.com/app", "example.com"):
            with mock.patch.dict(os.environ, {"TRADING_HUB_CORS_ORIGINS": bad}):
                with self.assertRaises(ValueError):
                    main.configured_cors_origins()

    def test_explicit_origin_list_is_used(self):
        with mock.patch.dict(os.environ, {"TRADING_HUB_CORS_ORIGINS": "https://user.github.io, http://localhost:5173"}):
            self.assertEqual(main.configured_cors_origins(), ["https://user.github.io", "http://localhost:5173"])


if __name__ == "__main__":
    unittest.main()
