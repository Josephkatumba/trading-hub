from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from performance import performance_report


class DailyPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        labels = ["WIN", "LOSS", "NO_HIT", "AMBIGUOUS", None]
        for index, label in enumerate(labels):
            self.events.append({"setup_id": f"stp_{index}", "observation_id": f"obs_{index}",
                "confirmed_at": f"2026-09-23T0{index}:00:00+00:00", "symbol": "XAUUSD" if index < 2 else "EURUSD",
                "setup_type": "REVERSAL", "timeframe": "M15"})
        self.outcomes = []
        for index, label in enumerate(labels[:-1]):
            self.outcomes.append({"record_type": "market_outcome", "setup_id": f"stp_{index}",
                "observation_id": f"obs_{index}", "horizon": "4h", "label": label})
        # Trade records with the same label are deliberately excluded.
        self.outcomes.append({"record_type": "trade_outcome", "setup_id": "stp_4",
                              "observation_id": "obs_4", "horizon": "4h", "label": "WIN"})
        self.snapshots = [{"record_type": "setup_snapshot", "setup_id": "stp_watch",
            "observed_at": "2026-09-23T09:00:00+00:00", "lifecycle_state": "ACTIVE",
            "rule_evidence": {"strategy_valid": False}}]

    def test_headline_metric_excludes_no_hit_ambiguous_and_pending(self):
        report = performance_report(self.events, self.outcomes, self.snapshots,
            report_date="2026-09-23", timezone_name="Africa/Nairobi")
        day = report["daily"][0]
        self.assertEqual(day["confirmed"], 5)
        self.assertEqual(day["wins"], 1)
        self.assertEqual(day["losses"], 1)
        self.assertEqual(day["pending"], 1)
        self.assertEqual(day["no_hit"], 1)
        self.assertEqual(day["ambiguous"], 1)
        self.assertEqual(day["win_rate_denominator"], 2)
        self.assertEqual(day["win_rate"], 50.0)
        self.assertEqual(day["watchlist"], 1)

    def test_all_four_horizons_and_historical_days_are_retained(self):
        report = performance_report(self.events, self.outcomes, self.snapshots,
            report_date="2026-09-23", days=7, timezone_name="Africa/Nairobi")
        self.assertEqual(report["available_horizons"], ["15m", "1h", "4h", "24h"])
        self.assertEqual(len(report["daily"]), 7)
        self.assertEqual(report["daily"][-1]["by_horizon"]["4h"]["win"], 1)
        self.assertEqual(report["summary"]["confirmed"], 5)
        self.assertEqual(report["timezone"], "Africa/Nairobi")

    def test_duplicate_confirmation_is_counted_once_per_episode(self):
        events = self.events + [dict(self.events[0])]
        day = performance_report(events, self.outcomes, self.snapshots,
            report_date="2026-09-23", timezone_name="Africa/Nairobi")["daily"][0]
        self.assertEqual(day["confirmed"], 5)


if __name__ == "__main__":
    unittest.main()
