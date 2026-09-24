from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = '''import pathlib, sys
import observations
root=pathlib.Path(sys.argv[1]); observations.DATA_DIR=root
observations.LOG_FILE=root/"snapshots.jsonl"; observations.LIFECYCLE_FILE=root/"lifecycle.jsonl"
observations.CONFIRMATIONS_FILE=root/"confirmations.jsonl"
def market():
 return {"symbol":"XAUUSD","state":"CONFIRMING","direction":"LONG","setup_family":"REVERSAL","timeframe":"M15","price":2650.0,"atr":5.0,"trendline_identity":{"orientation":"ASCENDING_SUPPORT","anchors":[{"time":"a","price":2640},{"time":"b","price":2645}]},"strategy_valid":True,"trendline_gate":True,"confirmation_alignment":True,"score":80,"rr":2.0}
'''


def run(directory: str) -> dict:
    result = subprocess.run([sys.executable, "-c", SCRIPT + '\n' +
        "m=market(); observations.record_markets([m]); sid=m['setup_id']; observations.record_markets([market()]); print(__import__('json').dumps({'setup_id':sid,'events':observations.confirmation_events(sid)}))",
        directory], cwd=BACKEND, text=True, capture_output=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout.splitlines()[-1])


class ConfirmationEventTests(unittest.TestCase):
    def test_one_event_per_setup_across_repeats_and_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            first = run(temp)
            second = run(temp)  # separate Python process, same JSONL persistence
            self.assertEqual(first["setup_id"], second["setup_id"])
            self.assertEqual(len(first["events"]), 1)
            self.assertEqual(len(second["events"]), 1)
            self.assertEqual(first["events"][0]["observation_id"], second["events"][0]["observation_id"])


if __name__ == "__main__":
    unittest.main()
