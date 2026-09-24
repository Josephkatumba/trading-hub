from __future__ import annotations

import json
import unittest
from urllib.error import URLError
from urllib.request import urlopen

BASE_URL = "http://127.0.0.1:8000"


def get_json(path: str) -> tuple[int, dict]:
    with urlopen(BASE_URL + path, timeout=15) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


try:
    get_json("/api/health")
    LIVE_BACKEND = True
except (URLError, TimeoutError, OSError):
    LIVE_BACKEND = False


@unittest.skipUnless(LIVE_BACKEND, "Live backend on port 8000 is required for API route regression checks")
class SetupApiRouteTests(unittest.TestCase):
    def test_setup_detail_and_analyst_return_success_for_persisted_setup(self):
        _, recent = get_json("/api/market/observations?limit=1000")
        snapshots = [row for row in recent.get("observations", [])
                     if row.get("record_type") == "setup_snapshot"]
        self.assertTrue(snapshots, "No persisted setup snapshot is available for route verification")
        snapshot = next((row for row in snapshots if row.get("invalidation_price") is not None
                         or (row.get("rule_evidence") or {}).get("invalidation_hint") is not None), snapshots[0])
        setup_id = snapshot["setup_id"]
        observation_id = snapshot["observation_id"]

        detail_status, detail = get_json(f"/api/market/setups/{setup_id}")
        self.assertEqual(detail_status, 200)
        self.assertTrue(any(row.get("observation_id") == observation_id
                            for row in detail["snapshots"]))
        self.assertIn("market_outcomes", detail)
        self.assertIn("trade_outcomes", detail)

        analyst_status, analyst = get_json(
            f"/api/market/setups/{setup_id}/analysis?observation_id={observation_id}")
        self.assertEqual(analyst_status, 200)
        self.assertEqual(analyst["setup_id"], setup_id)
        self.assertEqual(analyst["observation_id"], observation_id)
        self.assertIn(analyst["classification"], {"WATCH", "CONFIRMED"})


if __name__ == "__main__":
    unittest.main()
