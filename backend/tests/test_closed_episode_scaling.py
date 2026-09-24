"""Scan cost does not grow with the number of closed episodes.

Builds synthetic stores with 2,000 and 20,000 closed episodes (full-size
snapshot rows cloned from a real record_markets snapshot, each with its
lifecycle events, every fifth with a confirmation) plus the same open
episodes, then runs identical steady-state scans on both. Required:
  * a scan loads full rows only for open episodes (same count for both stores),
  * a scan never re-reads the observation, lifecycle or confirmation JSONL,
  * scan time at 20k closed is not ~10x the time at 2k (loose bound; the
    structural checks above are the precise ones).
"""
from __future__ import annotations

import copy
import json
import statistics
import sys
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_support as g  # noqa: E402

import observations  # noqa: E402
from episode_identity import trendline_identity  # noqa: E402

SYMBOLS = g.OFFICIAL_SCAN
OPEN_SYMBOLS = SYMBOLS[:3]


def scan_market(symbol: str, price: float = 2650.0) -> dict:
    return {"symbol": symbol, "timeframe": "M15", "direction": "LONG", "state": "DEVELOPING", "price": price,
            "atr": 5.0, "score": 70, "score_breakdown": {"trendline": 20}, "strategy_valid": False,
            "trendline_gate": True, "confirmation_alignment": False, "rr": None, "setup_family": "BREAK",
            "trendline_state": "BREAK", "setup": "Trendline break", "invalidation_hint": price - 20,
            "entry": price, "stop_loss": price - 20, "take_profit": price + 30,
            "trendline_identity": {"orientation": "DESCENDING_RESISTANCE", "anchors": [
                {"time": "2026-09-24T08:00:00Z", "price": price - 10}, {"time": "2026-09-24T09:00:00Z", "price": price - 5}]}}


def templates() -> tuple[dict, dict]:
    """One real snapshot row and lifecycle event written by record_markets."""
    with tempfile.TemporaryDirectory() as tmp, g.isolated_store(observations, Path(tmp)):
        observations.record_markets([scan_market("TEMPLATE")])
        snapshot = json.loads((Path(tmp) / "setup_observations.jsonl").read_text(encoding="utf-8").splitlines()[0])
        event = json.loads((Path(tmp) / "setup_lifecycle.jsonl").read_text(encoding="utf-8").splitlines()[0])
    return snapshot, event


def build_store(root: Path, closed: int) -> None:
    snapshot, event = templates()
    observations_out, lifecycle_out, confirmations_out = [], [], []
    for index in range(closed):
        symbol = SYMBOLS[index % len(SYMBOLS)]
        row = copy.deepcopy(snapshot)
        sid = f"stp_closed_{index:06d}"
        observed = g.BASE_NOW - timedelta(days=20) + timedelta(seconds=30 * index)
        row.update(setup_id=sid, observation_id=f"obs_closed_{index:06d}", symbol=symbol, broker_symbol=symbol,
                   observed_at=observed.isoformat(), direction="SHORT" if index % 2 else "LONG",
                   reference_price=1000.0 + index)  # far from the scanned prices: never near
        if index % 10 == 0:  # closed episodes without trendline geometry
            row["episode_identity"]["trendline_identity"] = None
        else:                # distinct trendlines that never recur in the scans
            row["episode_identity"]["trendline_identity"] = trendline_identity({"trendline_identity": {
                "orientation": "DESCENDING_RESISTANCE", "anchors": [{"time": observed.isoformat(), "price": index}]}})
        observations_out.append(row)
        closing = "EXPIRED" if index % 3 == 0 else "INVALIDATED"
        lifecycle_out.append({**event, "event_id": f"evt_d_{index:06d}", "setup_id": sid,
                              "occurred_at": observed.isoformat(), "from_state": None, "to_state": "DETECTED"})
        lifecycle_out.append({**event, "event_id": f"evt_c_{index:06d}", "setup_id": sid, "occurred_at": observed.isoformat(),
                              "from_state": "DETECTED", "to_state": closing, "reason_code": "DIRECTION_CHANGED"})
        if index % 5 == 0:
            confirmations_out.append({"record_type": "setup_confirmation", "schema_version": "1.0",
                                      "confirmation_event_id": f"cnf_{index:06d}", "setup_id": sid,
                                      "confirmed_at": observed.isoformat(), "observation_id": row["observation_id"],
                                      "symbol": symbol, "direction": row["direction"]})
    for index, symbol in enumerate(OPEN_SYMBOLS):  # the same open episodes in every store
        row = copy.deepcopy(snapshot)
        sid = f"stp_open_{index}"
        row.update(setup_id=sid, observation_id=f"obs_open_{index}", symbol=symbol, broker_symbol=symbol,
                   observed_at=(g.BASE_NOW - timedelta(minutes=15)).isoformat())
        observations_out.append(row)
        lifecycle_out.append({**event, "event_id": f"evt_open_{index}", "setup_id": sid})
    for name, rows in (("setup_observations.jsonl", observations_out), ("setup_lifecycle.jsonl", lifecycle_out),
                       ("setup_confirmations.jsonl", confirmations_out)):
        (root / name).write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def measure(closed: int, scans: int = 7) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_store(root, closed)
        with g.isolated_store(observations, root):
            index = observations._observation_index()
            start = time.perf_counter()
            observations.record_markets([scan_market(symbol) for symbol in SYMBOLS])  # first scan builds the indexes
            first = time.perf_counter() - start
            loaded, full_reads, timings = [], [], []
            real_load, real_read = index.load, observations._read_jsonl
            counter = {"rows": 0}

            def counting_load(positions):
                rows = real_load(positions)
                counter["rows"] += len(rows)
                return rows

            def recording_read(path):
                full_reads.append(Path(path).name)
                return real_read(path)
            with mock.patch.object(index, "load", counting_load), mock.patch.object(observations, "_read_jsonl", recording_read):
                for number in range(scans):
                    g.FrozenClock.current = g.BASE_NOW + timedelta(minutes=15 * (number + 1))
                    counter["rows"] = 0
                    start = time.perf_counter()
                    observations.record_markets([scan_market(symbol) for symbol in SYMBOLS])
                    timings.append(time.perf_counter() - start)
                    loaded.append(counter["rows"])
        return {"closed": closed, "first_scan_s": first, "median_scan_s": statistics.median(timings),
                "rows_loaded": loaded, "full_reads": full_reads,
                "store_mb": round((root / "setup_observations.jsonl").stat().st_size / 1e6, 1) if root.exists() else None}


class ClosedEpisodeScalingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.small = measure(2_000)
        cls.large = measure(20_000)
        for result in (cls.small, cls.large):
            print(f"\n  closed={result['closed']:>6}  first scan (index build) {result['first_scan_s']*1000:8.1f} ms"
                  f"  steady scan median {result['median_scan_s']*1000:6.2f} ms  rows loaded/scan {result['rows_loaded']}",
                  file=sys.stderr)

    def test_scans_load_full_rows_only_for_open_episodes(self):
        # 10 open episodes after the first scan (3 seeded + 7 opened), whatever the closed count.
        self.assertEqual(self.small["rows_loaded"], self.large["rows_loaded"])
        self.assertTrue(all(count == len(SYMBOLS) for count in self.large["rows_loaded"]), self.large["rows_loaded"])

    def test_scans_never_reread_the_jsonl_stores(self):
        self.assertEqual(self.small["full_reads"], [])
        self.assertEqual(self.large["full_reads"], [])

    def test_scan_time_does_not_grow_linearly_with_closed_episodes(self):
        # 10x the closed episodes; a linear scan would take ~10x as long.
        self.assertLess(self.large["median_scan_s"], 3 * self.small["median_scan_s"] + 0.010,
                        (self.small["median_scan_s"], self.large["median_scan_s"]))


if __name__ == "__main__":
    unittest.main()
