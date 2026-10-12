import os
import asyncio
import json
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storage_config import data_directory
import main
from store_audit import audit_store


async def get_ready():
    messages = []
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        messages.append(message)
    await main.app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                    "method": "GET", "scheme": "http", "path": "/api/ready", "raw_path": b"/api/ready",
                    "query_string": b"", "root_path": "", "headers": [],
                    "server": ("localhost", 8000), "client": ("localhost", 12345)}, receive, send)
    return messages[0]["status"], json.loads(messages[1]["body"])


class DeploymentTests(unittest.TestCase):
    def test_store_audit_reports_damaged_duplicate_and_missing_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            confirmation = {"setup_id": "s", "observation_id": "present"}
            outcome = {"setup_id": "s", "observation_id": "missing", "horizon": "1h", "label_definition": "v1"}
            (root / "setup_confirmations.jsonl").write_text(json.dumps(confirmation)+"\n", encoding="utf-8")
            (root / "market_outcomes.jsonl").write_text((json.dumps(outcome)+"\n")*2, encoding="utf-8")
            (root / "setup_observations.jsonl").write_bytes(b'{"observation_id":"present"}\n\xff\n')
            report = audit_store(root)
            self.assertEqual(report["setup_observations.jsonl"]["damaged_lines"], 1)
            self.assertEqual(report["market_outcomes.jsonl"]["duplicate_outcome_keys"], 1)
            self.assertEqual(report["integrity"], {"missing_confirmation_observation_ids": 0,
                                                  "missing_outcome_observation_ids": 1})

    def test_readiness_http_fails_closed_and_reports_scanner_state(self):
        with patch.object(main, "latest_scan", return_value=([], {"status": "STORAGE_ERROR", "market_count": 1},
                         {"status": "FRESH", "age_seconds": 1})):
            status, payload = asyncio.run(get_ready())
            self.assertEqual(status, 503)
            self.assertFalse(payload["execution_enabled"])
        with patch.object(main, "latest_scan", return_value=([], {"status": "CONNECTED", "market_count": 16},
                         {"status": "FRESH", "age_seconds": 30})):
            self.assertEqual(asyncio.run(get_ready())[0], 200)
        with patch.object(main, "latest_scan", return_value=([], {"status": "CONNECTED", "market_count": 16},
                         {"status": "STALE", "age_seconds": 600})):
            self.assertEqual(asyncio.run(get_ready())[0], 503)
        with patch.object(main, "latest_scan", return_value=([], {"status": "SCANNING", "market_count": 16},
                         {"status": "FRESH", "result_status": "CONNECTED", "age_seconds": 30})):
            self.assertEqual(asyncio.run(get_ready())[0], 200)

    def test_radar_does_not_hide_storage_errors_behind_available_prices(self):
        with patch.object(main, "latest_scan", return_value=([{"symbol": "EURUSD"}],
                         {"status": "STORAGE_ERROR", "error": "write failed"},
                         {"status": "FRESH", "result_status": "STORAGE_ERROR", "completed_at": None})):
            self.assertEqual(main.radar()["engine_status"], "STORAGE_ERROR")

    def test_default_preserves_existing_store(self):
        with patch.dict(os.environ, {"TRADING_HUB_DATA_DIR": ""}):
            self.assertEqual(data_directory(), Path(__file__).resolve().parents[1] / "data")

    def test_absolute_override_and_relative_rejection(self):
        root = str(Path(__file__).resolve().parent)
        with patch.dict(os.environ, {"TRADING_HUB_DATA_DIR": root}):
            self.assertEqual(data_directory(), Path(root))
        with patch.dict(os.environ, {"TRADING_HUB_DATA_DIR": "relative/data"}):
            with self.assertRaises(ValueError):
                data_directory()
