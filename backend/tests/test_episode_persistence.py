from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
BASE = '''import json, pathlib, sys
import observations
root=pathlib.Path(sys.argv[1]); observations.DATA_DIR=root
observations.LOG_FILE=root/"setup_observations.jsonl"; observations.LIFECYCLE_FILE=root/"setup_lifecycle.jsonl"
def m(a="08:00", b="09:00", price=2650.0):
 return {"symbol":"XAUUSD","state":"WATCHING","direction":"LONG","setup_family":"REVERSAL","trendline_state":"REVERSAL","timeframe":"M15","price":price,"atr":5.0,"score":65,"score_breakdown":{"trendline":20},"invalidation_hint":2635.0,"trendline_identity":{"orientation":"ASCENDING_SUPPORT","anchors":[{"time":"2026-09-23T"+a+":00Z","price":2640.0},{"time":"2026-09-23T"+b+":00Z","price":2645.0}]}}
'''


def run_isolated(directory: str, body: str) -> dict:
    completed = subprocess.run([sys.executable, "-c", BASE + "\n" + body, directory],
                               cwd=BACKEND, text=True, capture_output=True, check=True)
    return json.loads(completed.stdout.strip().splitlines()[-1])


class EpisodePersistenceTests(unittest.TestCase):
    def test_id_survives_restart_and_distinct_episode_gets_new_id(self):
        with tempfile.TemporaryDirectory() as temp:
            first = run_isolated(temp, "first=m(); observations.record_markets([first]); print(json.dumps({'id':first['setup_id']}))")
            first_id = first["id"]
            # A fresh Python process simulates backend restart against the same JSONL store.
            second = run_isolated(temp, "same=m('10:00','11:00'); observations.record_markets([same]); same_id=same['setup_id']; fresh=m('10:00','11:00'); fresh['direction']='SHORT'; fresh['invalidation_hint']=2665.0; observations.record_markets([fresh]); print(json.dumps({'same':same_id,'new':fresh['setup_id'],'events':len(observations.lifecycle_events(same_id)),'snapshots':len(observations.setup_history(same_id))}))")
            self.assertEqual(second["same"], first_id)
            self.assertNotEqual(second["new"], first_id)
            self.assertGreaterEqual(second["events"], 2)
            self.assertGreaterEqual(second["snapshots"], 2)

    def test_nearby_trendline_revisions_keep_episode_id(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run_isolated(temp, "first=m(); observations.record_markets([first]); sid=first['setup_id']; revised=m('08:15','09:15',2651.0); observations.record_markets([revised]); print(json.dumps({'first':sid,'second':revised['setup_id']}))")
            self.assertEqual(result["first"], result["second"])

    def test_legacy_line_is_unchanged_and_adopted(self):
        with tempfile.TemporaryDirectory() as temp:
            # Recent enough to stay inside the 24h episode gap; a fixed date here
            # made this test start failing a day after it was written.
            observed = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
            legacy = {"observation_id": "legacy-ob-1", "observed_at": observed,
                      "symbol": "XAUUSD", "state": "WATCHING", "direction": "LONG", "price": 2650.0,
                      "score": 60, "setup_family": None, "trendline_state": "WATCHING"}
            path = Path(temp) / "setup_observations.jsonl"
            original = (json.dumps(legacy, separators=(",", ":")) + "\n").encode()
            path.write_bytes(original)
            result = run_isolated(temp, "current=m(); observations.record_markets([current]); print(json.dumps({'id':current['setup_id']}))")
            self.assertTrue(path.read_bytes().startswith(original))
            self.assertTrue(result["id"].startswith("stp_legacy_"))


if __name__ == "__main__":
    unittest.main()
